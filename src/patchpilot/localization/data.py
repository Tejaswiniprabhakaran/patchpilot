"""Build the fault-localization dataset from the SWE-bench training split (A1).

For each selected training instance:

* the query is the issue text;
* candidate files are the gold files (from ``SWE-bench_oracle``) plus the BM25-retrieved files
  (from ``SWE-bench_bm25_27K``); a file is positive if the gold patch edits it;
* candidate functions are the functions of those files; a function is positive if the gold patch
  edits a line inside it.

Files are represented by a *skeleton* (path + class/function signatures + first docstring line)
and functions by their qualified name + source, both short enough for a 512-token encoder. The
agent builds exactly the same views from the sandbox at inference time.

Splits are by repository, so no repository contributes to more than one split.
"""

from __future__ import annotations

import ast
import contextlib
import gzip
import json
import random
import re
from collections import defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from patchpilot.agent.localize import is_test_path
from patchpilot.localization.code_units import MODULE, edited_units, extract_units
from patchpilot.localization.patches import edited_lines

SOURCE_DATASET = "princeton-nlp/SWE-bench"
ORACLE_DATASET = "princeton-nlp/SWE-bench_oracle"
BM25_DATASET = "princeton-nlp/SWE-bench_bm25_27K"
SEED = 42
PER_REPO_CAP = 400
MAX_QUERY_CHARS = 4000
MAX_SKELETON_CHARS = 3000
MAX_UNIT_CHARS = 2000
MAX_UNITS_PER_FILE = 40

_FILE_BLOCK = re.compile(
    r"\[start of (?P<path>[^\]]+)\]\n(?P<body>.*?)\n?\[end of (?P=path)\]", re.S
)
_LINE_NO = re.compile(r"^\d+ ?", re.M)


@dataclass
class Candidate:
    cid: str  # file path, or "path::qualname" for functions
    text: str
    label: int


@dataclass
class LocExample:
    instance_id: str
    repo: str
    split: str
    query: str
    gold_files: list[str]
    gold_units: list[str]
    files: list[Candidate] = field(default_factory=list)
    units: list[Candidate] = field(default_factory=list)


# ---------------------------------------------------------------------- text views


def parse_code_blocks(text: str) -> dict[str, str]:
    """Files embedded in a SWE-bench retrieval prompt, with the line-number prefixes removed."""
    return {m["path"]: _LINE_NO.sub("", m["body"]) for m in _FILE_BLOCK.finditer(text)}


def file_skeleton(path: str, source: str, max_chars: int = MAX_SKELETON_CHARS) -> str:
    """Path plus the signatures of every class and function (with a one-line docstring)."""
    lines = [path]
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return (path + "\n" + source)[:max_chars]

    def visit(node: ast.AST, indent: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
                if isinstance(child, ast.ClassDef):
                    kind, args = "class", ""
                else:
                    kind, args = "def", f"({ast.unparse(child.args)})"
                doc = (ast.get_docstring(child) or "").strip().splitlines()
                summary = f"  # {doc[0][:80]}" if doc else ""
                lines.append(f"{indent}{kind} {child.name}{args}{summary}")
                visit(child, indent + "    ")

    visit(tree, "")
    return "\n".join(lines)[:max_chars]


def unit_text(path: str, name: str, source: str, max_chars: int = MAX_UNIT_CHARS) -> str:
    return f"{path}::{name}\n{source}"[:max_chars]


# ---------------------------------------------------------------------- examples


def function_targets(gold_units: Iterable[str]) -> list[str]:
    """Gold units that are real functions.

    An edit to module-level code is labelled ``path::<module>``. No candidate is ever a whole
    module, so such labels are left out of function-level scoring instead of counting as
    automatic misses for every method.
    """
    return [unit for unit in gold_units if not unit.endswith(f"::{MODULE}")]


def build_example(
    row: dict[str, Any], gold_sources: dict[str, str], retrieved: dict[str, str], split: str
) -> LocExample | None:
    """One training example, or None if the gold patch edits no existing non-test Python file."""
    edits = edited_lines(row["patch"])
    gold_files = sorted(
        p
        for p, e in edits.items()
        if p.endswith(".py") and not is_test_path(p) and not e.is_new_file and p in gold_sources
    )
    if not gold_files:
        return None

    sources = {p: c for p, c in retrieved.items() if p.endswith(".py") and not is_test_path(p)}
    sources.update({p: gold_sources[p] for p in gold_files})

    example = LocExample(
        instance_id=row["instance_id"],
        repo=row["repo"],
        split=split,
        query=row["problem_statement"][:MAX_QUERY_CHARS],
        gold_files=gold_files,
        gold_units=[],
    )
    for path in sorted(sources):
        example.files.append(
            Candidate(path, file_skeleton(path, sources[path]), int(path in gold_files))
        )
        units = extract_units(path, sources[path])
        gold_names = set(edited_units(units, edits[path].lines)) if path in gold_files else set()
        example.gold_units += [f"{path}::{name}" for name in sorted(gold_names)]
        # Every function of a gold file (positives and in-file hard negatives); a capped number
        # from other files.
        keep = units if path in gold_files else units[:MAX_UNITS_PER_FILE]
        for unit in keep:
            example.units.append(
                Candidate(
                    unit.unit_id,
                    unit_text(path, unit.name, unit.source),
                    int(unit.name in gold_names),
                )
            )
    return example


# ---------------------------------------------------------------------- selection & splits


def select_instances(
    rows: Iterable[dict[str, Any]], per_repo_cap: int = PER_REPO_CAP, seed: int = SEED
) -> dict[str, str]:
    """Seeded sample of at most ``per_repo_cap`` instance ids per repo -> repo."""
    by_repo: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        by_repo[row["repo"]].append(row["instance_id"])
    rng = random.Random(seed)
    chosen: dict[str, str] = {}
    for repo in sorted(by_repo):
        ids = sorted(by_repo[repo])
        for instance_id in rng.sample(ids, min(per_repo_cap, len(ids))):
            chosen[instance_id] = repo
    return chosen


def split_repos(
    repo_sizes: dict[str, int], val_share: float = 0.1, test_share: float = 0.1, seed: int = SEED
) -> dict[str, str]:
    """Assign whole repositories to train/val/test so each held-out split has ~its share."""
    repos = sorted(repo_sizes)
    random.Random(seed).shuffle(repos)
    total = sum(repo_sizes.values())
    assignment: dict[str, str] = {}
    counts = {"test": 0, "val": 0}
    for repo in repos:
        if counts["test"] < test_share * total:
            split = "test"
        elif counts["val"] < val_share * total:
            split = "val"
        else:
            split = "train"
        assignment[repo] = split
        if split in counts:
            counts[split] += repo_sizes[repo]
    return assignment


# ---------------------------------------------------------------------- I/O


def write_examples(examples: Iterable[LocExample], out_dir: Path) -> dict[str, int]:
    out_dir.mkdir(parents=True, exist_ok=True)
    splits = ("train", "val", "test")
    counts = dict.fromkeys(splits, 0)
    with contextlib.ExitStack() as stack:
        handles = {
            s: stack.enter_context(gzip.open(out_dir / f"{s}.jsonl.gz", "wt", encoding="utf-8"))
            for s in splits
        }
        for example in examples:
            handles[example.split].write(json.dumps(asdict(example)) + "\n")
            counts[example.split] += 1
    return counts


def read_examples(path: Path) -> Iterator[LocExample]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            data = json.loads(line)
            data["files"] = [Candidate(**c) for c in data["files"]]
            data["units"] = [Candidate(**c) for c in data["units"]]
            yield LocExample(**data)
