"""Tell infrastructure failures (machine slept, model server stalled) apart from agent failures.

The rule is fixed in advance and ignores whether the bug was fixed, so re-running the flagged
rows cannot bias results toward any configuration (decisions D13).
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Any

STALL_S = 1800.0
INFRA_ERRORS = ("APITimeoutError", "APIConnectionError", "Timeout", "ConnectionError")


def slowest_llm_call(trajectory_path: Path) -> float:
    if not trajectory_path.exists():
        return 0.0
    with gzip.open(trajectory_path, "rt", encoding="utf-8") as handle:
        steps = json.load(handle)["steps"]
    return float(max((s["duration_s"] for s in steps if s["kind"] == "llm"), default=0.0))


def infra_reason(row: dict[str, Any], trajectories: Path, stall_s: float = STALL_S) -> str | None:
    """Why ``row`` is an infrastructure failure, or None if it is a genuine agent result."""
    error = row.get("error") or ""
    if any(marker in error for marker in INFRA_ERRORS):
        return f"model server error: {error[:200]}"
    slowest = slowest_llm_call(trajectories / f"{row['run_id']}.json.gz")
    if slowest > stall_s:
        return f"model call took {slowest:.0f} s (> {stall_s:.0f} s)"
    return None


def split_rows(
    rows: list[dict[str, Any]],
    trajectories: Path,
    already_requeued: set[str],
    stall_s: float = STALL_S,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(rows to keep, rows to re-queue). An instance is re-queued at most once."""
    keep, requeue = [], []
    for row in rows:
        reason = infra_reason(row, trajectories, stall_s)
        if reason and row["instance_id"] not in already_requeued:
            requeue.append(row | {"requeue_reason": reason})
        else:
            keep.append(row)
    return keep, requeue
