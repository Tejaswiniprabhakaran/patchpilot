"""Read runs, trajectories and summary tables for the dashboard (S5). No writes."""

from __future__ import annotations

import csv
import gzip
import json
from pathlib import Path
from typing import Any

from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import DiffLexer

BENCHMARKS = ("quixbugs", "swebench-lite")


def list_runs(results_dir: Path, runs_dir: Path) -> list[dict[str, Any]]:
    """Every saved run: experiment results first, then ad-hoc `patchpilot fix` runs."""
    runs: list[dict[str, Any]] = []
    if results_dir.exists():
        for exp_dir in sorted(p for p in results_dir.iterdir() if p.is_dir()):
            for benchmark in BENCHMARKS:
                path = exp_dir / f"{benchmark}.jsonl"
                if not path.exists():
                    continue
                for line in path.read_text(encoding="utf-8").splitlines():
                    if line.strip():
                        row = json.loads(line)
                        runs.append(_summary(row, exp_dir.name))
    if runs_dir.exists():
        for path in sorted(runs_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            data = json.loads(path.read_text(encoding="utf-8"))
            result = data.get("result", {})
            runs.append(
                _summary(
                    {
                        "benchmark": data["benchmark"],
                        "instance_id": data["instance_id"],
                        "run_id": data["run_id"],
                        **result,
                    },
                    "fix",
                )
            )
    return runs


def _summary(row: dict[str, Any], experiment: str) -> dict[str, Any]:
    return {
        "experiment": experiment,
        "benchmark": row.get("benchmark", ""),
        "instance_id": row.get("instance_id", ""),
        "run_id": row.get("run_id", ""),
        "resolved": bool(row.get("resolved")),
        "attempts_used": row.get("attempts_used", 0),
        "wall_s": row.get("wall_s"),
        "llm_calls": row.get("llm_calls", 0),
        "tokens": (row.get("prompt_tokens") or 0) + (row.get("completion_tokens") or 0),
        "error": row.get("error"),
    }


def load_run(
    results_dir: Path, runs_dir: Path, experiment: str, run_id: str
) -> dict[str, Any] | None:
    """A full trajectory, from results/<experiment>/trajectories or runs/ (experiment 'fix')."""
    if "/" in run_id or "\\" in run_id or ".." in run_id or "/" in experiment or ".." in experiment:
        return None
    if experiment == "fix":
        path = runs_dir / f"{run_id}.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
    path = results_dir / experiment / "trajectories" / f"{run_id}.json.gz"
    if not path.exists():
        return None
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        data: dict[str, Any] = json.load(handle)
    return data


def diff_html(diff: str) -> str:
    """A unified diff as syntax-highlighted HTML (classes styled in static/style.css)."""
    if not diff.strip():
        return "<p class='muted'>No patch.</p>"
    return str(highlight(diff, DiffLexer(), HtmlFormatter(cssclass="diff")))


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))
