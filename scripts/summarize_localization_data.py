"""Function-level label statistics of the built localization dataset.

Reports, per split, how many instances have at least one real gold *function* and how many only
edit module-level code (labelled ``path::<module>``, which is never a candidate and so is left out
of function-level scoring; see ``localization.data.function_targets``).

Usage:
    python scripts/summarize_localization_data.py
Writes results/localization/dataset_function_stats.json.
"""

from __future__ import annotations

import json
import statistics
from pathlib import Path

from patchpilot.localization import data as locdata

DATA = Path("data/processed/localization")
OUTPUT = Path("results/localization/dataset_function_stats.json")


def main() -> None:
    report = {}
    for split in ("train", "val", "test"):
        examples = list(locdata.read_examples(DATA / f"{split}.jsonl.gz"))
        functions = [locdata.function_targets(ex.gold_units) for ex in examples]
        module_labels = sum(
            len(ex.gold_units) - len(f) for ex, f in zip(examples, functions, strict=True)
        )
        report[split] = {
            "examples": len(examples),
            "examples_with_gold_function": sum(1 for f in functions if f),
            "examples_module_level_only": sum(
                1 for ex, f in zip(examples, functions, strict=True) if ex.gold_units and not f
            ),
            "examples_without_any_unit_label": sum(1 for ex in examples if not ex.gold_units),
            "gold_functions": sum(len(f) for f in functions),
            "module_level_labels": module_labels,
            "median_file_candidates": statistics.median(len(ex.files) for ex in examples),
            "median_function_candidates": statistics.median(len(ex.units) for ex in examples),
        }
    OUTPUT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
