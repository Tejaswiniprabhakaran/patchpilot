"""Compare the classifier's labels with the owner's manual labels (A5).

Usage:
    python scripts/failure_agreement.py
Writes results/analysis/agreement.json (accuracy, Cohen's kappa, confusion matrix).
"""

from __future__ import annotations

import json

from patchpilot.analysis.report import OUT, agreement, read_jsonl


def main() -> None:
    result = agreement(
        read_jsonl(OUT / "failure_labels.jsonl"), read_jsonl(OUT / "manual_labels.jsonl")
    )
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "agreement.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
