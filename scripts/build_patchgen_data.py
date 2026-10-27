"""Build the patch-generation fine-tuning dataset (A2).

Uses the same seeded selection and repository splits as the localization data, and the gold
files cached by scripts/build_localization_data.py, so nothing new is downloaded except the
small SWE-bench metadata (already in the Hugging Face cache).

Usage:
    python scripts/build_patchgen_data.py [--oracle-cache ../patchpilot-loc/data/cache/oracle]
Writes data/processed/patchgen/{train,val,test}.jsonl.gz (git-ignored) and
results/patchgen/dataset_stats.json (committed).
"""

from __future__ import annotations

import argparse
import contextlib
import gzip
import json
import logging
from collections import Counter
from pathlib import Path
from typing import Any

from patchpilot.localization import data as locdata
from patchpilot.patchgen.data import build_example

STATS = Path("results/patchgen/dataset_stats.json")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--oracle-cache", type=Path, default=Path("data/cache/oracle"))
    parser.add_argument("--out", type=Path, default=Path("data/processed/patchgen"))
    parser.add_argument("--stats", type=Path, default=STATS)
    parser.add_argument("--limit", type=int, help="stop after this many selected instances")
    args = parser.parse_args()
    logging.disable(logging.WARNING)

    from datasets import load_dataset

    rows = {r["instance_id"]: r for r in load_dataset(locdata.SOURCE_DATASET, split="train")}
    chosen = locdata.select_instances(rows.values())
    splits = locdata.split_repos(Counter(chosen.values()))

    skipped: Counter[str] = Counter()
    kept: Counter[str] = Counter()
    chars: list[int] = []
    args.out.mkdir(parents=True, exist_ok=True)
    with contextlib.ExitStack() as stack:
        handles = {
            s: stack.enter_context(gzip.open(args.out / f"{s}.jsonl.gz", "wt", encoding="utf-8"))
            for s in ("train", "val", "test")
        }
        for index, instance_id in enumerate(sorted(chosen)):
            if args.limit and index >= args.limit:
                break
            cache = args.oracle_cache / f"{instance_id}.json.gz"
            if not cache.exists():
                skipped["no_oracle"] += 1
                continue
            with gzip.open(cache, "rt", encoding="utf-8") as handle:
                gold = json.load(handle)
            row = rows[instance_id]
            example, reason = build_example(row, gold, splits[row["repo"]])
            if example is None:
                skipped[reason] += 1
                continue
            handles[example["split"]].write(json.dumps(example) + "\n")
            kept[example["split"]] += 1
            chars.append(sum(len(m["content"]) for m in example["messages"][1:]))

    summary: dict[str, Any] = {
        "source": [locdata.SOURCE_DATASET, locdata.ORACLE_DATASET],
        "seed": locdata.SEED,
        "per_repo_cap": locdata.PER_REPO_CAP,
        "selected_instances": len(chosen),
        "examples": dict(kept),
        "skipped": dict(skipped),
        "user_plus_assistant_chars": {
            "median": sorted(chars)[len(chars) // 2] if chars else 0,
            "max": max(chars, default=0),
        },
        "repo_split": splits,
    }
    args.stats.parent.mkdir(parents=True, exist_ok=True)
    args.stats.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8", newline="\n")
    keys = ("examples", "skipped", "user_plus_assistant_chars")
    print(json.dumps({k: summary[k] for k in keys}, indent=2))


if __name__ == "__main__":
    main()
