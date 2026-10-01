"""Check that every benchmark instance fails when buggy and passes with its gold patch.

Usage:
    python scripts/sanity_gold_patches.py --benchmark quixbugs
    python scripts/sanity_gold_patches.py --benchmark swebench-lite

Appends one JSON line per instance to results/sanity_gold_patches.jsonl. Instances already
present in that file are skipped, so an interrupted run can be resumed.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from patchpilot.benchmarks import BenchmarkInstance
from patchpilot.benchmarks.sanity import check_instance

OUTPUT = Path("results/sanity_gold_patches.jsonl")


def load(benchmark: str) -> list[BenchmarkInstance]:
    if benchmark == "quixbugs":
        from patchpilot.benchmarks import quixbugs

        quixbugs.ensure_downloaded()
        quixbugs.build_image()
        return quixbugs.load_instances()
    if benchmark == "swebench-lite":
        from patchpilot.benchmarks import swebench

        return swebench.load_subset()
    raise SystemExit(f"unknown benchmark: {benchmark}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--benchmark", required=True, choices=["quixbugs", "swebench-lite"])
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--instance", action="append", help="only check these instance ids")
    parser.add_argument(
        "--prune", action="store_true", help="remove each SWE-bench image after use (D5)"
    )
    args = parser.parse_args()

    done: set[tuple[str, str]] = set()
    if args.output.exists():
        for line in args.output.read_text(encoding="utf-8").splitlines():
            record = json.loads(line)
            done.add((record["benchmark"], record["instance_id"]))
    args.output.parent.mkdir(parents=True, exist_ok=True)

    instances = load(args.benchmark)
    if args.instance:
        instances = [i for i in instances if i.instance_id in set(args.instance)]
    valid = checked = 0
    with args.output.open("a", encoding="utf-8", newline="\n") as out:
        for instance in instances:
            if (instance.benchmark, instance.instance_id) in done:
                continue
            try:
                if instance.benchmark == "swebench-lite":
                    from patchpilot.benchmarks import swebench

                    with swebench.pulled_image(instance.image, prune=args.prune):
                        record = check_instance(instance)
                else:
                    record = check_instance(instance)
            except Exception as exc:  # one broken instance must not stop the whole run
                record = {
                    "benchmark": instance.benchmark,
                    "instance_id": instance.instance_id,
                    "image": instance.image,
                    "valid": False,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            out.write(json.dumps(record) + "\n")
            out.flush()
            valid += record["valid"]
            checked += 1
            status = "ok  " if record["valid"] else "FAIL"
            print(f"{status} {instance.instance_id} {record.get('error', '')}", flush=True)
    print(f"{valid} valid out of {checked} newly checked")


if __name__ == "__main__":
    main()
