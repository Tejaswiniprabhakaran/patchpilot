"""Tell infrastructure failures (machine slept, model server stalled) apart from agent failures.

The rule is fixed in advance and ignores whether the bug was fixed, so re-running the flagged
rows cannot bias results toward any configuration (decisions D13, D17).
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Any

STALL_S = 1800.0
INFRA_ERRORS = ("APITimeoutError", "APIConnectionError", "Timeout", "ConnectionError")
# The server stops a few tokens short of a full window (4,092-4,095 of 4,096 were seen).
WINDOW_MARGIN = 8


def llm_steps(trajectory_path: Path) -> list[dict[str, Any]]:
    if not trajectory_path.exists():
        return []
    with gzip.open(trajectory_path, "rt", encoding="utf-8") as handle:
        steps = json.load(handle)["steps"]
    return [s for s in steps if s["kind"] == "llm"]


def slowest_llm_call(trajectory_path: Path) -> float:
    return float(max((s["duration_s"] for s in llm_steps(trajectory_path)), default=0.0))


def fullest_llm_call(trajectory_path: Path) -> int:
    """Largest prompt + completion token count of any model call in the trajectory."""
    totals = (
        (s.get("meta", {}).get("prompt_tokens") or 0)
        + (s.get("meta", {}).get("completion_tokens") or 0)
        for s in llm_steps(trajectory_path)
    )
    return max(totals, default=0)


def infra_reason(
    row: dict[str, Any],
    trajectories: Path,
    stall_s: float = STALL_S,
    context_window: int | None = None,
) -> str | None:
    """Why ``row`` is an infrastructure failure, or None if it is a genuine agent result.

    With ``context_window`` (the window the server really used), a run with a model call that
    filled it is flagged too: the server cut that answer short, not the agent.
    """
    error = row.get("error") or ""
    if any(marker in error for marker in INFRA_ERRORS):
        return f"model server error: {error[:200]}"
    trajectory = trajectories / f"{row['run_id']}.json.gz"
    slowest = slowest_llm_call(trajectory)
    if slowest > stall_s:
        return f"model call took {slowest:.0f} s (> {stall_s:.0f} s)"
    if context_window:
        fullest = fullest_llm_call(trajectory)
        if fullest >= context_window - WINDOW_MARGIN:
            return (
                f"a model call filled the {context_window}-token context window ({fullest} tokens)"
            )
    return None


def split_rows(
    rows: list[dict[str, Any]],
    trajectories: Path,
    already_requeued: set[str],
    stall_s: float = STALL_S,
    context_window: int | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(rows to keep, rows to re-queue). An instance is re-queued at most once."""
    keep, requeue = [], []
    for row in rows:
        reason = infra_reason(row, trajectories, stall_s, context_window)
        if reason and row["instance_id"] not in already_requeued:
            requeue.append(row | {"requeue_reason": reason})
        else:
            keep.append(row)
    return keep, requeue
