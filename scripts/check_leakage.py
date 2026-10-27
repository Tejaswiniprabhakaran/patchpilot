"""Prove the localization/patch training data never overlaps the evaluation data.

Compares every SWE-bench *training* instance selected for our datasets with every SWE-bench Lite
*test* instance (which contains both evaluation subsets) on four keys:

    repository, instance id, normalised issue text, normalised gold patch

Usage:
    python scripts/check_leakage.py
Writes results/leakage_check.json and exits non-zero if any overlap is found.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import sys
from pathlib import Path
from typing import Any

from patchpilot.localization import data as locdata

OUTPUT = Path("results/leakage_check.json")
EVAL_DATASET = "princeton-nlp/SWE-bench_Lite"
EVAL_SUBSETS = ["configs/swebench_lite_subset_50.json", "configs/swebench_lite_subset_10.json"]


def fingerprint(text: str) -> str:
    """Hash of text with whitespace and case normalised (catches copy-pasted duplicates)."""
    normal = re.sub(r"\s+", " ", text).strip().lower()
    return hashlib.sha256(normal.encode("utf-8")).hexdigest()


def overlaps(train: list[dict[str, Any]], test: list[dict[str, Any]]) -> dict[str, Any]:
    keys = {
        "repo": lambda r: r["repo"],
        "instance_id": lambda r: r["instance_id"],
        "issue_text": lambda r: fingerprint(r["problem_statement"]),
        "gold_patch": lambda r: fingerprint(r["patch"]),
    }
    report: dict[str, Any] = {}
    for name, key in keys.items():
        train_keys = {key(r) for r in train}
        hits = sorted(r["instance_id"] for r in test if key(r) in train_keys)
        report[name] = {"overlapping_eval_instances": len(hits), "examples": hits[:10]}
    return report


def main() -> None:
    logging.disable(logging.WARNING)
    from datasets import load_dataset

    train_rows = list(load_dataset(locdata.SOURCE_DATASET, split="train"))
    chosen = locdata.select_instances(train_rows)
    train = [r for r in train_rows if r["instance_id"] in chosen]
    test = [dict(r) for r in load_dataset(EVAL_DATASET, split="test")]

    subset_ids: set[str] = set()
    for path in EVAL_SUBSETS:
        subset_ids |= set(json.loads(Path(path).read_text(encoding="utf-8"))["instance_ids"])

    report = {
        "train_source": locdata.SOURCE_DATASET,
        "train_instances_checked": len(train),
        "train_repos": sorted({r["repo"] for r in train}),
        "all_train_split_instances_checked": len(train_rows),
        "eval_source": EVAL_DATASET,
        "eval_instances_checked": len(test),
        "eval_repos": sorted({r["repo"] for r in test}),
        "eval_subset_instances": len(subset_ids),
        "selected_train_vs_eval": overlaps(train, test),
        # Stricter: the WHOLE training split, in case a later dataset uses more of it.
        "full_train_split_vs_eval": overlaps(train_rows, test),
    }
    leaks = sum(
        v["overlapping_eval_instances"]
        for section in ("selected_train_vs_eval", "full_train_split_vs_eval")
        for v in report[section].values()
    )
    report["leak_free"] = leaks == 0
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(
        json.dumps(
            {k: v for k, v in report.items() if "vs_eval" in k or k == "leak_free"}, indent=2
        )
    )
    sys.exit(0 if report["leak_free"] else 1)


if __name__ == "__main__":
    main()
