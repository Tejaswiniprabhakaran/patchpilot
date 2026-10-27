"""Load experiment results from ``results/`` and apply the scoring rules.

* SWE-bench Lite instances that failed the gold-patch sanity check are excluded (D11).
* Rows re-queued as infrastructure failures live in ``infra_failures.jsonl`` and are ignored (D13).
* An experiment counts as complete only when every scored instance has a row.
"""

from __future__ import annotations

import gzip
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

RESULTS = Path("results")
SANITY = RESULTS / "sanity_gold_patches.jsonl"
EXPECTED = {"quixbugs": 40, "swebench-lite": 10}  # evaluation set sizes (decisions D12)


@dataclass
class ExperimentResults:
    experiment: str
    benchmark: str
    rows: dict[str, dict[str, Any]] = field(default_factory=dict)  # instance_id -> row
    excluded: list[str] = field(default_factory=list)
    source: str = ""

    @property
    def complete(self) -> bool:
        return len(self.rows) >= EXPECTED.get(self.benchmark, 0) - len(self.excluded)

    def resolved(self) -> dict[str, bool]:
        return {i: bool(r.get("resolved")) for i, r in self.rows.items()}


def invalid_instances(sanity_file: Path = SANITY) -> set[str]:
    """Instances whose gold patch does not pass in the sandbox (decisions D11)."""
    if not sanity_file.exists():
        return set()
    return {
        record["instance_id"]
        for record in map(json.loads, sanity_file.read_text(encoding="utf-8").splitlines())
        if not record.get("valid")
    }


def load_experiment(
    experiment: str, benchmark: str, results_dir: Path = RESULTS, sanity_file: Path = SANITY
) -> ExperimentResults:
    path = results_dir / experiment / f"{benchmark}.jsonl"
    out = ExperimentResults(experiment, benchmark, source=str(path).replace("\\", "/"))
    if not path.exists():
        return out
    invalid = invalid_instances(sanity_file)
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row["instance_id"] in invalid:
            if row["instance_id"] not in out.excluded:
                out.excluded.append(row["instance_id"])
            continue
        out.rows[row["instance_id"]] = row  # a later row for the same instance wins
    return out


def load_trajectory(experiment: str, run_id: str, results_dir: Path = RESULTS) -> dict[str, Any]:
    path = results_dir / experiment / "trajectories" / f"{run_id}.json.gz"
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        data: dict[str, Any] = json.load(handle)
    return data


def gold_files(benchmark: str, instance_id: str) -> list[str]:
    """Source files the reference fix edits (used to score the agent's localization)."""
    if benchmark == "quixbugs":
        return [f"python_programs/{instance_id}.py"]
    from patchpilot.agent.localize import is_test_path
    from patchpilot.benchmarks import swebench

    patch = swebench.load_instance(instance_id).gold_patch
    return [p for p in swebench.patched_paths(patch) if not is_test_path(p)]
