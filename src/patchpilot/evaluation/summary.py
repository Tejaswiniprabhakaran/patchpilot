"""Turn raw experiment results into the tables used by the README and the report (A4).

Every number comes from ``results/<experiment>/<benchmark>.jsonl``; experiments that have not run
(or not finished) are reported as such and are left out of the paired tests.
"""

from __future__ import annotations

import csv
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from patchpilot.evaluation.results import RESULTS, SANITY, ExperimentResults, load_experiment
from patchpilot.evaluation.stats import (
    Rate,
    describe_numbers,
    paired_compare,
    resolved_within,
)

BENCHMARKS = ("quixbugs", "swebench-lite")


@dataclass(frozen=True)
class Config:
    experiment: str  # results folder
    label: str  # name used in tables
    description: str
    attempts: int | None = None  # report this run "as if" capped at k attempts (E3 -> E4/E5)


CONFIGS = [
    Config("B0", "B0", "LLM-search localization, base Gemma 4 E4B, 3 attempts"),
    Config("B0", "B0@1", "B0 counted at its first attempt (no retries)", attempts=1),
    Config("E1", "E1", "trained ranker, base Gemma 4 E4B, 3 attempts"),
    Config("E1", "E1@1", "E1 counted at its first attempt (no retries)", attempts=1),
]
# E2-E4 (fine-tuned patch generator) and G1 (Gemini reference) were dropped (decisions D18).
COMPARISONS = [  # (a, b, research question)
    ("B0", "E1", "RQ2: trained ranker vs LLM search (base model)"),
    ("B0@1", "B0", "RQ4: retries with feedback (3 attempts) vs 1 attempt (B0)"),
    ("E1@1", "E1", "RQ4: retries with feedback (3 attempts) vs 1 attempt (E1)"),
]
# Runs whose "resolved within k attempts" curve is reported, and the k values shown.
CURVE_K = {"B0": (1, 2, 3), "E1": (1, 2, 3)}


def outcome(config: Config, results: ExperimentResults) -> dict[str, bool]:
    """Per-instance resolution, applying the attempt cap for derived configurations."""
    if config.attempts is None:
        return results.resolved()
    return {i: bool(resolved_within([r], config.attempts).k) for i, r in results.rows.items()}


def build_tables(
    results_dir: Path = RESULTS,
    sanity_file: Path = SANITY,
    loader: Callable[..., ExperimentResults] = load_experiment,
) -> dict[str, list[dict[str, Any]]]:
    rates: list[dict[str, Any]] = []
    outcomes: dict[tuple[str, str], dict[str, bool]] = {}
    complete: dict[tuple[str, str], bool] = {}
    cost: list[dict[str, Any]] = []
    curve: list[dict[str, Any]] = []
    for benchmark in BENCHMARKS:
        for config in CONFIGS:
            res = loader(config.experiment, benchmark, results_dir, sanity_file)
            key = (config.label, benchmark)
            if not res.rows:
                rates.append(_rate_row(config, benchmark, res, None, "TODO: not yet run"))
                continue
            resolved = outcome(config, res)
            outcomes[key] = resolved
            complete[key] = res.complete
            status = (
                "complete" if res.complete else f"incomplete ({len(res.rows)} instances so far)"
            )
            rate = Rate(sum(resolved.values()), len(resolved))
            rates.append(_rate_row(config, benchmark, res, rate, status))
            if config.attempts in (None, 3):
                rows = list(res.rows.values())
                cost.append(
                    {
                        "config": config.label,
                        "benchmark": benchmark,
                        "status": status,
                        "source": res.source,
                        **{
                            f"wall_s_{k}": v
                            for k, v in describe_numbers(r.get("wall_s") for r in rows).items()
                            if k != "n"
                        },
                        **{
                            f"llm_calls_{k}": v
                            for k, v in describe_numbers(r.get("llm_calls") for r in rows).items()
                            if k != "n"
                        },
                        "prompt_tokens_mean": describe_numbers(
                            r.get("prompt_tokens") for r in rows
                        )["mean"],
                        "completion_tokens_mean": describe_numbers(
                            r.get("completion_tokens") for r in rows
                        )["mean"],
                        "attempts_used_mean": describe_numbers(
                            r.get("attempts_used") for r in rows
                        )["mean"],
                    }
                )
            if config.label in CURVE_K and config.attempts in (None, 3):
                for k in CURVE_K[config.label]:
                    within = resolved_within(res.rows.values(), k)
                    curve.append(
                        {
                            "config": config.label,
                            "benchmark": benchmark,
                            "attempts": k,
                            "resolved": within.k,
                            "n": within.n,
                            "rate": round(within.value, 4),
                            "status": status,
                            "source": res.source,
                        }
                    )

    tests: list[dict[str, Any]] = []
    for benchmark in BENCHMARKS:
        for a, b, question in COMPARISONS:
            ka, kb = (a, benchmark), (b, benchmark)
            if not (complete.get(ka) and complete.get(kb)):
                tests.append(
                    {
                        "benchmark": benchmark,
                        "question": question,
                        "a": a,
                        "b": b,
                        "status": "TODO: needs both experiments complete",
                    }
                )
                continue
            comparison = paired_compare(a, outcomes[ka], b, outcomes[kb])
            tests.append(
                {
                    "benchmark": benchmark,
                    "question": question,
                    "status": "done",
                    **comparison.as_row(),
                }
            )
    return {"resolve_rates": rates, "paired_tests": tests, "retries_curve": curve, "cost": cost}


def _rate_row(
    config: Config, benchmark: str, res: ExperimentResults, rate: Rate | None, status: str
) -> dict[str, Any]:
    low, high = rate.interval() if rate else (None, None)
    return {
        "config": config.label,
        "benchmark": benchmark,
        "description": config.description,
        "status": status,
        "resolved": rate.k if rate else None,
        "n": rate.n if rate else None,
        "rate": round(rate.value, 4) if rate else None,
        "ci95_low": round(low, 4) if low is not None else None,
        "ci95_high": round(high, 4) if high is not None else None,
        "excluded": " ".join(res.excluded),
        "source": res.source,
    }


def write_tables(tables: dict[str, list[dict[str, Any]]], out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for name, rows in tables.items():
        path = out_dir / f"{name}.csv"
        fields: list[str] = []
        for row in rows:
            fields += [k for k in row if k not in fields]
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields or ["empty"], lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
        written.append(path)
    return written


def _row(*cells: object) -> str:
    return "| " + " | ".join(str(c) for c in cells) + " |"


def markdown(tables: dict[str, list[dict[str, Any]]]) -> str:
    """Human-readable summary with the source of every number."""
    lines = [
        "# Results summary",
        "",
        "Generated by `scripts/summarize_results.py` from `results/`.",
        "",
        "## Resolve rate",
        "",
        _row("Config", "Benchmark", "Resolved", "Rate (95% CI)", "Status", "Source"),
        _row(*["---"] * 6),
    ]
    for r in tables["resolve_rates"]:
        source = f"`{r['source']}`"
        if r["n"]:
            rate = f"{r['rate']:.1%} ({r['ci95_low']:.1%}-{r['ci95_high']:.1%})"
            resolved = f"{r['resolved']}/{r['n']}"
            lines.append(_row(r["config"], r["benchmark"], resolved, rate, r["status"], source))
        else:
            lines.append(_row(r["config"], r["benchmark"], "-", "-", r["status"], source))

    lines += [
        "",
        "## Paired comparisons (exact McNemar test)",
        "",
        _row("Benchmark", "Question", "A only", "B only", "p", "Status"),
        _row(*["---"] * 6),
    ]
    for t in tables["paired_tests"]:
        if t["status"] == "done":
            cells = (t["a_only"], t["b_only"], t["mcnemar_exact_p"], "done")
        else:
            cells = ("-", "-", "-", t["status"])
        lines.append(_row(t["benchmark"], t["question"], *cells))

    lines += ["", "## Retries curve (resolved within k attempts)", ""]
    if tables["retries_curve"]:
        lines += [_row("Config", "Benchmark", "k", "Resolved", "Rate"), _row(*["---"] * 5)]
        for c in tables["retries_curve"]:
            resolved = f"{c['resolved']}/{c['n']}"
            lines.append(
                _row(c["config"], c["benchmark"], c["attempts"], resolved, f"{c['rate']:.1%}")
            )
    else:
        lines.append("TODO: not yet run (needs B0, E1 or E3 results).")
    lines.append("")
    return "\n".join(lines)
