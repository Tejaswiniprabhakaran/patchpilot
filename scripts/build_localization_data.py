"""Build the fault-localization dataset (A1) from the SWE-bench training split.

Usage:
    python scripts/build_localization_data.py                 # full build
    python scripts/build_localization_data.py --per-repo-cap 3 --out data/processed/loc_small

Writes data/processed/localization/{train,val,test}.jsonl.gz (git-ignored) and
results/localization/dataset_stats.json (committed). The build is deterministic (seed 42).
"""

from __future__ import annotations

import argparse
import gzip
import json
import logging
from collections import Counter
from pathlib import Path
from typing import Any

from patchpilot.localization import data as locdata

CACHE = Path("data/cache/oracle")
STATS = Path("results/localization/dataset_stats.json")


def stream(name: str) -> Any:
    from datasets import load_dataset

    return load_dataset(name, split="train", streaming=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--per-repo-cap", type=int, default=locdata.PER_REPO_CAP)
    parser.add_argument("--out", type=Path, default=Path("data/processed/localization"))
    parser.add_argument("--stats", type=Path, default=STATS)
    args = parser.parse_args()
    logging.disable(logging.WARNING)

    from datasets import load_dataset

    meta = load_dataset(locdata.SOURCE_DATASET, split="train")
    rows = {r["instance_id"]: r for r in meta}
    chosen = locdata.select_instances(rows.values(), per_repo_cap=args.per_repo_cap)
    splits = locdata.split_repos(Counter(chosen.values()))
    print(f"selected {len(chosen)} instances from {len(splits)} repos", flush=True)

    # Pass 1: cache the gold files' sources from the oracle dataset.
    CACHE.mkdir(parents=True, exist_ok=True)
    cached = 0
    for row in stream(locdata.ORACLE_DATASET):
        instance_id = row["instance_id"]
        path = CACHE / f"{instance_id}.json.gz"
        if instance_id in chosen and not path.exists():
            with gzip.open(path, "wt", encoding="utf-8") as handle:
                json.dump(locdata.parse_code_blocks(row["text"]), handle)
        cached += instance_id in chosen
    print(f"oracle sources cached for {cached} instances", flush=True)

    # Pass 2: stream BM25 retrievals and build examples.
    skipped: Counter[str] = Counter()

    def examples() -> Any:
        for row in stream(locdata.BM25_DATASET):
            instance_id = row["instance_id"]
            if instance_id not in chosen:
                continue
            gold_path = CACHE / f"{instance_id}.json.gz"
            if not gold_path.exists():
                skipped["no_oracle"] += 1
                continue
            with gzip.open(gold_path, "rt", encoding="utf-8") as handle:
                gold = json.load(handle)
            example = locdata.build_example(
                rows[instance_id], gold, locdata.parse_code_blocks(row["text"]), splits[row["repo"]]
            )
            if example is None:
                skipped["no_python_source_edit"] += 1
                continue
            stats.append(
                {
                    "split": example.split,
                    "repo": example.repo,
                    "files": len(example.files),
                    "gold_files": len(example.gold_files),
                    "units": len(example.units),
                    "gold_units": len(example.gold_units),
                }
            )
            yield example

    stats: list[dict[str, Any]] = []
    counts = locdata.write_examples(examples(), args.out)

    summary: dict[str, Any] = {
        "source": [locdata.SOURCE_DATASET, locdata.ORACLE_DATASET, locdata.BM25_DATASET],
        "seed": locdata.SEED,
        "per_repo_cap": args.per_repo_cap,
        "selected_instances": len(chosen),
        "examples": counts,
        "skipped": dict(skipped),
        "repo_split": splits,
        "per_split": {},
    }
    for split in ("train", "val", "test"):
        part = [s for s in stats if s["split"] == split]
        if not part:
            continue
        summary["per_split"][split] = {
            "examples": len(part),
            "repos": len({s["repo"] for s in part}),
            "file_candidates": sum(s["files"] for s in part),
            "positive_files": sum(s["gold_files"] for s in part),
            "function_candidates": sum(s["units"] for s in part),
            "positive_functions": sum(s["gold_units"] for s in part),
        }
    args.stats.parent.mkdir(parents=True, exist_ok=True)
    args.stats.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(summary["per_split"], indent=2))
    print(f"skipped: {dict(skipped)}")


if __name__ == "__main__":
    main()
