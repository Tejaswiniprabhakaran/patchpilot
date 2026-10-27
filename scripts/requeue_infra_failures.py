"""Re-queue experiment rows that failed because of the infrastructure, not the agent (D13).

A row is an infrastructure failure if, regardless of whether the bug was fixed:
  * its run ended with a model-server error (timeout, connection error), or
  * any single model call took longer than 1800 s, which on this laptop means the machine
    slept or the model server stalled.

Such rows are moved from results/<exp>/<benchmark>.jsonl to results/<exp>/infra_failures.jsonl
(their trajectories stay where they are), so `patchpilot eval` runs those instances again.
Each instance is re-queued at most once: a second infrastructure failure stays in the results
and is reported as an environment error. Run it only when no experiment is writing the file.

Usage:
    python scripts/requeue_infra_failures.py results/B0/quixbugs.jsonl [--dry-run]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from patchpilot.evaluation.infra import STALL_S, split_rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results_file", type=Path)
    parser.add_argument("--stall-s", type=float, default=STALL_S)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    exp_dir = args.results_file.parent
    log = exp_dir / "infra_failures.jsonl"
    already = set()
    if log.exists():
        already = {json.loads(line)["instance_id"] for line in log.read_text().splitlines()}
    rows = [json.loads(line) for line in args.results_file.read_text().splitlines() if line]

    keep, requeue = split_rows(rows, exp_dir / "trajectories", already, args.stall_s)
    for row in requeue:
        print(f"re-queue {row['instance_id']}: {row['requeue_reason']}")
    if args.dry_run or not requeue:
        print(f"{len(requeue)} row(s) to re-queue" + (" (dry run)" if args.dry_run else ""))
        return
    with log.open("a", encoding="utf-8", newline="\n") as handle:
        for row in requeue:
            handle.write(json.dumps(row) + "\n")
    args.results_file.write_text(
        "".join(json.dumps(r) + "\n" for r in keep), encoding="utf-8", newline="\n"
    )
    print(f"moved {len(requeue)} row(s) to {log}")


if __name__ == "__main__":
    main()
