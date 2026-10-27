"""Classify every unresolved run and write the failure taxonomy (A5).

Usage:
    python scripts/classify_failures.py            # rules only
    python scripts/classify_failures.py --judge    # rules + LLM judge for uncertain categories
Writes results/analysis/failure_labels.jsonl, taxonomy.csv and taxonomy.md (with case studies).
"""

from __future__ import annotations

import argparse
from collections import Counter

from patchpilot.analysis.report import OUT, classify_all, taxonomy, write_jsonl, write_taxonomy


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--judge", action="store_true", help="ask the LLM judge about uncertain cases"
    )
    parser.add_argument("--model", default="gemma4:e4b")
    parser.add_argument("--base-url", default="http://localhost:11434/v1")
    args = parser.parse_args()

    llm = None
    if args.judge:
        from patchpilot.llm import LLMConfig, OpenAICompatibleClient

        llm = OpenAICompatibleClient(
            LLMConfig(model=args.model, base_url=args.base_url, reasoning_effort="none")
        )
    labels = classify_all(llm=llm)
    write_jsonl(OUT / "failure_labels.jsonl", labels)
    rows = taxonomy(labels)
    write_taxonomy(rows, labels)
    counts = dict(Counter(lab["category"] for lab in labels))
    print(f"{len(labels)} unresolved runs classified: {counts}")
    print(f"wrote {OUT / 'failure_labels.jsonl'}, {OUT / 'taxonomy.csv'}, {OUT / 'taxonomy.md'}")


if __name__ == "__main__":
    main()
