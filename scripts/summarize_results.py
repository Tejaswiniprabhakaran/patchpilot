"""Build the results tables (resolve rates, paired McNemar tests, retries curve, cost).

Usage:
    python scripts/summarize_results.py
Writes results/summary/{resolve_rates,paired_tests,retries_curve,cost}.csv and
results/summary/summary.md. Experiments that have not run are reported as TODO.
"""

from __future__ import annotations

from pathlib import Path

from patchpilot.evaluation.summary import build_tables, markdown, write_tables

OUT = Path("results/summary")


def main() -> None:
    tables = build_tables()
    for path in write_tables(tables, OUT):
        print(f"wrote {path}")
    text = markdown(tables)
    (OUT / "summary.md").write_text(text, encoding="utf-8", newline="\n")
    print(text)


if __name__ == "__main__":
    main()
