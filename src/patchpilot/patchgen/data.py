"""Build supervised fine-tuning data for the patch generator (A2).

Each example is one chat in exactly the agent's prompt format:

    system:    the agent's SYSTEM prompt (asks for SEARCH/REPLACE blocks)
    user:      bug report + the tests added by the fix + the gold files trimmed around the edit
    assistant: the developers' fix rewritten as SEARCH/REPLACE blocks

so fine-tuning teaches both how to fix and the exact output format the agent parses.

Source: the SWE-bench *training* split (repositories disjoint from SWE-bench Lite), the same
seeded selection and repository splits as the localization data, and the gold files' contents
cached from ``SWE-bench_oracle`` by ``scripts/build_localization_data.py``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from patchpilot.agent import prompts
from patchpilot.agent.localize import is_test_path
from patchpilot.tools.toolbox import apply_search_replace

MAX_EXTRA_CONTEXT = 12  # lines added around a SEARCH block until it is unique in its file
CONTEXT_WINDOW = 15  # lines shown above and below each edited region
MAX_FILE_LINES_WHOLE = 150
MAX_TEST_CHARS = 1500
MAX_PROBLEM_CHARS = 3000
MAX_FILES = 1  # SWE-bench Lite: gold patches edit a single file
MAX_HUNKS = 3  # ... with at most three hunks
MAX_CHARS = 10_000  # user + assistant, about 2,800 Gemma tokens

_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


@dataclass(frozen=True)
class Hunk:
    old_start: int  # 1-based line in the original file
    old: list[str]  # original lines covered by the hunk (context + removed)
    new: list[str]  # replacement lines (context + added)


@dataclass(frozen=True)
class Block:
    path: str
    search: str
    replace: str


def parse_hunks(diff: str) -> dict[str, list[Hunk]]:
    """Hunks per modified file. New, deleted and renamed-without-change files are skipped."""
    files: dict[str, list[Hunk]] = {}
    path: str | None = None
    new_file = False
    old: list[str] = []
    new: list[str] = []
    start = 0

    def flush() -> None:
        if path is not None and (old or new):
            files.setdefault(path, []).append(Hunk(start, list(old), list(new)))

    for line in diff.splitlines():
        if line.startswith("--- "):
            flush()
            old, new, path = [], [], None
            new_file = line.strip() == "--- /dev/null"
            continue
        if line.startswith("+++ "):
            target = line[4:].strip()
            path = None if new_file or target == "/dev/null" else target.removeprefix("b/")
            continue
        match = _HUNK.match(line)
        if match:
            flush()
            old, new = [], []
            start = int(match.group(1))
            continue
        if path is None or line.startswith(("diff --git", "index ", "\\ No newline")):
            continue
        marker, text = (line[0], line[1:]) if line else (" ", "")
        if marker in " -":
            old.append(text)
        if marker in " +":
            new.append(text)
    flush()
    return files


def apply_hunks(source: str, hunks: list[Hunk]) -> str:
    """Apply hunks to ``source`` exactly as ``git apply`` would (used to check our blocks)."""
    lines = source.splitlines()
    for hunk in sorted(hunks, key=lambda h: h.old_start, reverse=True):
        begin = hunk.old_start - 1 if hunk.old else hunk.old_start
        if lines[begin : begin + len(hunk.old)] != hunk.old:
            raise ValueError(f"hunk at line {hunk.old_start} does not match the source")
        lines[begin : begin + len(hunk.old)] = hunk.new
    return "\n".join(lines) + ("\n" if source.endswith("\n") else "")


def hunks_to_blocks(path: str, source: str, hunks: list[Hunk]) -> list[Block] | None:
    """SEARCH/REPLACE blocks that reproduce the hunks, each SEARCH unique in the file.

    Returns None when a block cannot be made unique or the result differs from ``git apply``.
    """
    lines = source.splitlines()
    blocks: list[Block] = []
    for hunk in hunks:
        if not hunk.old:
            return None  # a pure insertion has nothing to search for
        begin = hunk.old_start - 1
        old, new = list(hunk.old), list(hunk.new)
        before = after = 0
        while "\n".join(lines).count("\n".join(old)) != 1:
            # Grow the block by one real file line on each side until it is unique.
            grown = False
            if begin - before - 1 >= 0 and before < MAX_EXTRA_CONTEXT:
                before += 1
                old.insert(0, lines[begin - before])
                new.insert(0, lines[begin - before])
                grown = True
            end = begin + len(hunk.old) + after
            if end < len(lines) and after < MAX_EXTRA_CONTEXT:
                after += 1
                old.append(lines[end])
                new.append(lines[end])
                grown = True
            if not grown:
                return None
        blocks.append(Block(path, "\n".join(old) + "\n", "\n".join(new) + "\n"))

    # The blocks must turn the original into exactly what git apply produces.
    expected = apply_hunks(source, hunks)
    text = source
    for block in blocks:
        updated, _ = apply_search_replace(text, block.search, block.replace)
        if updated is None:
            return None
        text = updated
    return blocks if text.rstrip("\n") == expected.rstrip("\n") else None


def render_blocks(blocks: list[Block]) -> str:
    return "\n".join(
        f"{b.path}\n<<<<<<< SEARCH\n{b.search}=======\n{b.replace}>>>>>>> REPLACE\n" for b in blocks
    )


def trimmed_context(path: str, source: str, hunks: list[Hunk]) -> str:
    """The file as the agent shows it: numbered lines, whole if short, else windows."""
    lines = [f"{n:6d}  {line}" for n, line in enumerate(source.splitlines(), start=1)]
    if len(lines) <= MAX_FILE_LINES_WHOLE:
        return f"### {path}\n" + "\n".join(lines)
    keep: set[int] = set()
    for hunk in hunks:
        first = hunk.old_start - 1
        last = first + max(len(hunk.old), 1)
        keep.update(range(max(0, first - CONTEXT_WINDOW), min(len(lines), last + CONTEXT_WINDOW)))
    shown, previous = [], -2
    for index in sorted(keep):
        if index != previous + 1:
            shown.append("   ...")
        shown.append(lines[index])
        previous = index
    return f"### {path} (excerpts; line numbers on the left)\n" + "\n".join(shown)


def build_example(
    row: dict[str, Any], gold_sources: dict[str, str], split: str
) -> tuple[dict[str, Any] | None, str]:
    """(example, "") or (None, reason it was skipped)."""
    hunks = {
        p: h
        for p, h in parse_hunks(row["patch"]).items()
        if p.endswith(".py") and not is_test_path(p)
    }
    if not hunks:
        return None, "no_python_source_edit"
    # Same shape as SWE-bench Lite's own selection: one edited file, at most three hunks.
    if len(hunks) > MAX_FILES or sum(len(h) for h in hunks.values()) > MAX_HUNKS:
        return None, "not_lite_like"
    if any(p not in gold_sources for p in hunks):
        return None, "missing_source"
    blocks: list[Block] = []
    for path in sorted(hunks):
        try:
            converted = hunks_to_blocks(path, gold_sources[path], hunks[path])
        except (ValueError, IndexError):
            converted = None
        if converted is None:
            return None, "not_convertible"
        blocks += converted

    context = "\n\n".join(trimmed_context(p, gold_sources[p], hunks[p]) for p in sorted(hunks))
    tests = "Tests added by the fix (they fail before it):\n" + row["test_patch"][:MAX_TEST_CHARS]
    problem = row["problem_statement"][:MAX_PROBLEM_CHARS]
    user = prompts.REPAIR.format(problem=problem, tests=tests, context=context)
    assistant = "Fix:\n\n" + render_blocks(blocks)
    if len(user) + len(assistant) > MAX_CHARS:
        return None, "too_long"
    return {
        "instance_id": row["instance_id"],
        "repo": row["repo"],
        "split": split,
        "files": sorted(hunks),
        "messages": [
            {"role": "system", "content": prompts.SYSTEM},
            {"role": "user", "content": user},
            {"role": "assistant", "content": assistant},
        ],
    }, ""
