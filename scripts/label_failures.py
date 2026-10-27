"""Label a random sample of failed runs by hand, blind to the classifier (A5).

Usage (in a normal terminal, from the repo root):
    python scripts/classify_failures.py      # first, so there are failures to sample
    python scripts/label_failures.py         # then label; type a number, 's' to skip, 'q' to quit

For each failure you see the bug report, the developers' fix, the agent's final patch and the
last test run, but NOT the classifier's answer. Labels are saved after every answer to
results/analysis/manual_labels.jsonl, so you can stop and resume at any time. The sample is seeded
(30 runs by default), so it does not change between sessions.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime

from patchpilot.analysis.failures import CATEGORIES, DESCRIPTIONS
from patchpilot.analysis.report import OUT, describe_for_labelling, read_jsonl, sample_for_labelling


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n", type=int, default=30)
    args = parser.parse_args()

    labels = read_jsonl(OUT / "failure_labels.jsonl")
    if not labels:
        raise SystemExit("run scripts/classify_failures.py first")
    manual_path = OUT / "manual_labels.jsonl"
    done = {m["run_id"] for m in read_jsonl(manual_path)}
    sample = sample_for_labelling(labels, args.n)
    todo = [lab for lab in sample if lab["run_id"] not in done]
    print(f"{len(sample) - len(todo)} of {len(sample)} already labelled; {len(todo)} to go.\n")

    menu = "\n".join(f"  {i}. {DESCRIPTIONS[c]}" for i, c in enumerate(CATEGORIES, start=1))
    for position, lab in enumerate(todo, start=1):
        print("\n" + "=" * 100)
        print(f"[{position}/{len(todo)}]")
        print(describe_for_labelling(lab))
        print("Why did this run fail?\n" + menu)
        while True:
            answer = input("Your label (number, s = skip, q = quit): ").strip().lower()
            if answer == "q":
                return
            if answer == "s":
                break
            if answer.isdigit() and 1 <= int(answer) <= len(CATEGORIES):
                record = {
                    "run_id": lab["run_id"],
                    "experiment": lab["experiment"],
                    "benchmark": lab["benchmark"],
                    "instance_id": lab["instance_id"],
                    "category": CATEGORIES[int(answer) - 1],
                    "labelled_at": datetime.now(UTC).isoformat(timespec="seconds"),
                }
                with manual_path.open("a", encoding="utf-8", newline="\n") as handle:
                    handle.write(json.dumps(record) + "\n")
                break
            print("Please type a number from the list, s or q.")
    print("\nDone. Now run: python scripts/failure_agreement.py")


if __name__ == "__main__":
    main()
