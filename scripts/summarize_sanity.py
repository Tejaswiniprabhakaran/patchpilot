"""Summarise results/sanity_gold_patches.jsonl per benchmark into results/sanity_summary.csv.

Usage:
    python scripts/summarize_sanity.py
"""

from __future__ import annotations

import csv
import json
import statistics
from pathlib import Path

SOURCE = Path("results/sanity_gold_patches.jsonl")
OUTPUT = Path("results/sanity_summary.csv")


def main() -> None:
    rows = [json.loads(line) for line in SOURCE.read_text(encoding="utf-8").splitlines() if line]
    out = []
    for benchmark in sorted({r["benchmark"] for r in rows}):
        subset = [r for r in rows if r["benchmark"] == benchmark]
        durations = [r["gold_duration_s"] for r in subset if "gold_duration_s" in r]
        out.append(
            {
                "benchmark": benchmark,
                "instances": len(subset),
                "buggy_fails": sum(bool(r.get("buggy_fails")) for r in subset),
                "gold_resolved": sum(bool(r.get("gold_resolved")) for r in subset),
                "valid": sum(bool(r["valid"]) for r in subset),
                "errors": sum("error" in r for r in subset),
                "median_gold_test_s": round(statistics.median(durations), 2),
                "max_gold_test_s": max(durations),
                "invalid_ids": " ".join(r["instance_id"] for r in subset if not r["valid"]),
            }
        )
    with OUTPUT.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(out[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(out)
    for row in out:
        print(row)


if __name__ == "__main__":
    main()
