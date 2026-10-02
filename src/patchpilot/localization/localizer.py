"""The trained-ranker localizer used by E1, E3 and E4 (A1 + A3 in the agent).

    every Python file in the repo --BM25--> shortlist of 50 files
        --cross-encoder over file skeletons--> top-k files
        --cross-encoder over their functions--> most suspicious functions

It implements the agent's ``Localizer`` interface, so B0 -> E1 changes exactly one thing.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any, Protocol

from patchpilot.agent.localize import Localization, is_test_path
from patchpilot.agent.trajectory import Timer, Trajectory
from patchpilot.benchmarks import BenchmarkInstance
from patchpilot.localization.bm25 import BM25Ranker, document_text
from patchpilot.localization.code_units import extract_units
from patchpilot.localization.data import file_skeleton, unit_text
from patchpilot.sandbox import DockerSandbox
from patchpilot.tools import Toolbox

MAX_FILE_BYTES = 300_000

# Runs inside the container: dump every tracked .py file as JSON {path: text}.
_DUMP = r"""
import json, subprocess, sys
paths = subprocess.run(["git", "ls-files", "-z", "*.py"], capture_output=True).stdout.split(b"\0")
out = {}
for raw in paths:
    if not raw:
        continue
    path = raw.decode("utf-8", "replace")
    try:
        with open(path, "rb") as f:
            data = f.read(MAX_BYTES + 1)
    except OSError:
        continue
    if len(data) <= MAX_BYTES:
        out[path] = data.decode("utf-8", "replace")
sys.stdout.write(json.dumps(out))
""".replace("MAX_BYTES", str(MAX_FILE_BYTES))


class Ranker(Protocol):
    name: str

    def rank(
        self, query: str, doc_ids: Sequence[str], texts: Sequence[str]
    ) -> list[tuple[str, float]]: ...


def repo_python_files(sandbox: DockerSandbox) -> dict[str, str]:
    """Every tracked Python file in the checkout (files over 300 kB are skipped)."""
    result = sandbox.exec(f"python - <<'PYEOF'\n{_DUMP}\nPYEOF", truncate=False)
    start = result.output.find("{")
    if not result.ok or start == -1:
        raise RuntimeError(f"could not list repository files: {result.output[-500:]}")
    files: dict[str, str] = json.loads(result.output[start:])
    return files


class RankerLocalizer:
    name = "ranker"

    def __init__(
        self,
        file_ranker: Ranker,
        unit_ranker: Ranker | None = None,
        top_k: int = 3,
        shortlist: int = 50,
        top_units: int = 5,
    ) -> None:
        self.file_ranker = file_ranker
        self.unit_ranker = unit_ranker or file_ranker
        self.top_k = top_k
        self.shortlist = shortlist
        self.top_units = top_units

    def localize(
        self,
        instance: BenchmarkInstance,
        tools: Toolbox,
        test_summary: str,
        trajectory: Trajectory,
    ) -> Localization:
        with Timer() as timer:
            all_files = repo_python_files(tools.sandbox)
            files = {
                p: c
                for p, c in all_files.items()
                if not is_test_path(p) and p not in instance.protected_paths
            }
            # BM25 sees the failing-test output too (tracebacks name files and functions); the
            # cross-encoder sees the issue text, exactly as in training.
            bm25 = BM25Ranker(list(files), [document_text(p, c) for p, c in files.items()])
            shortlist = [p for p, _ in bm25.rank(f"{instance.problem_statement}\n{test_summary}")]
            shortlist = shortlist[: self.shortlist]
            ranked_files = self.file_ranker.rank(
                instance.problem_statement,
                shortlist,
                [file_skeleton(p, files[p]) for p in shortlist],
            )
            top_files = [p for p, _ in ranked_files[: self.top_k]]

            units = [u for p in top_files for u in extract_units(p, files[p])]
            ranked_units = (
                self.unit_ranker.rank(
                    instance.problem_statement,
                    [u.unit_id for u in units],
                    [unit_text(u.path, u.name, u.source) for u in units],
                )
                if units
                else []
            )
        top_units = [uid for uid, _ in ranked_units[: self.top_units]]
        details: dict[str, Any] = {
            "repo_files": len(all_files),
            "candidate_files": len(files),
            "bm25_top10": shortlist[:10],
            "ranked_files": [(p, round(s, 4)) for p, s in ranked_files[:10]],
            "ranked_units": [(u, round(s, 4)) for u, s in ranked_units[:10]],
        }
        trajectory.add(
            "note",
            "localization",
            {"localizer": self.name, "ranker": self.file_ranker.name},
            "\n".join(top_files),
            bool(top_files),
            timer.elapsed,
            **details,
        )
        return Localization(
            files=top_files,
            keywords=[uid.split("::", 1)[1].split(".")[-1] for uid in top_units],
            details=details,
        )
