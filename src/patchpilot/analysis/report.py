"""Run the failure classifier over saved experiments and summarise it (A5).

Outputs (all under results/analysis/):
    failure_labels.jsonl   one classification per unresolved run
    taxonomy.csv / .md     counts per experiment, benchmark and category, plus case studies
    manual_labels.jsonl    written by scripts/label_failures.py (the owner's blind labels)
    agreement.json         classifier vs manual labels: accuracy, Cohen's kappa, confusion matrix
"""

from __future__ import annotations

import csv
import json
import random
from collections import Counter
from collections.abc import Iterator
from dataclasses import asdict
from pathlib import Path
from typing import Any

from patchpilot.agent.localize import is_test_path
from patchpilot.analysis.failures import CATEGORIES, DESCRIPTIONS, Classification, cohen_kappa
from patchpilot.analysis.judge import classify_with_judge, last_tests, problem_text
from patchpilot.evaluation.results import RESULTS, load_experiment, load_trajectory
from patchpilot.llm import LLMClient

OUT = RESULTS / "analysis"
BENCHMARKS = ("quixbugs", "swebench-lite")


def gold_for(benchmark: str, instance_id: str) -> tuple[str, list[str]]:
    """(gold patch, gold source files) for an instance."""
    if benchmark == "quixbugs":
        from patchpilot.benchmarks import quixbugs

        return quixbugs.load_instance(instance_id).gold_patch, [f"python_programs/{instance_id}.py"]
    from patchpilot.benchmarks import swebench

    patch = swebench.load_instance(instance_id).gold_patch
    return patch, [p for p in swebench.patched_paths(patch) if not is_test_path(p)]


def failed_runs(
    results_dir: Path = RESULTS,
) -> Iterator[tuple[str, str, bool, dict[str, Any]]]:
    """(experiment, benchmark, experiment complete?, trajectory) for every unresolved run."""
    for exp_dir in sorted(p for p in results_dir.iterdir() if p.is_dir()):
        for benchmark in BENCHMARKS:
            res = load_experiment(exp_dir.name, benchmark, results_dir)
            for row in res.rows.values():
                if not row.get("resolved"):
                    trajectory = load_trajectory(exp_dir.name, row["run_id"], results_dir)
                    yield exp_dir.name, benchmark, res.complete, trajectory


def classify_all(results_dir: Path = RESULTS, llm: LLMClient | None = None) -> list[dict[str, Any]]:
    labels = []
    for experiment, benchmark, complete, trajectory in failed_runs(results_dir):
        gold_patch, gold_files = gold_for(benchmark, trajectory["instance_id"])
        result = classify_with_judge(trajectory, gold_patch, gold_files, llm)
        labels.append(
            {
                "experiment": experiment,
                "benchmark": benchmark,
                "experiment_status": "complete" if complete else "incomplete",
                **asdict(result),
            }
        )
    return labels


def taxonomy(labels: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups = Counter((lab["experiment"], lab["benchmark"]) for lab in labels)
    status = {(lab["experiment"], lab["benchmark"]): lab.get("experiment_status") for lab in labels}
    counts = Counter((lab["experiment"], lab["benchmark"], lab["category"]) for lab in labels)
    rows = []
    for (experiment, benchmark), total in sorted(groups.items()):
        for category in CATEGORIES:
            n = counts.get((experiment, benchmark, category), 0)
            if n:
                rows.append(
                    {
                        "experiment": experiment,
                        "benchmark": benchmark,
                        "category": category,
                        "description": DESCRIPTIONS[category],
                        "count": n,
                        "failed_runs": total,
                        "share": round(n / total, 4),
                        "experiment_status": status[(experiment, benchmark)],
                    }
                )
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8", newline="\n")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def write_taxonomy(
    rows: list[dict[str, Any]],
    labels: list[dict[str, Any]],
    out: Path = OUT,
    results_dir: Path = RESULTS,
) -> None:
    out.mkdir(parents=True, exist_ok=True)
    with (out / "taxonomy.csv").open("w", encoding="utf-8", newline="") as handle:
        fields = [
            "experiment",
            "benchmark",
            "category",
            "description",
            "count",
            "failed_runs",
            "share",
            "experiment_status",
        ]
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    lines = [
        "# Failure taxonomy",
        "",
        "Generated by `scripts/classify_failures.py` from the saved trajectories.",
        "",
    ]
    if not rows:
        lines.append("TODO: no unresolved runs to analyse yet.")
    else:
        lines += [
            "| Experiment | Benchmark | Category | Count | Share of failures |",
            "|---|---|---|---|---|",
        ]
        for r in rows:
            incomplete = r.get("experiment_status") != "complete"
            cells = [
                r["experiment"] + (" (incomplete)" if incomplete else ""),
                r["benchmark"],
                r["description"],
                f"{r['count']}/{r['failed_runs']}",
                f"{r['share']:.0%}",
            ]
            lines.append("| " + " | ".join(cells) + " |")
        lines += ["", "## Case studies", "", *case_studies(labels, results_dir)]
    (out / "taxonomy.md").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def case_studies(
    labels: list[dict[str, Any]], results_dir: Path = RESULTS, limit: int = 4
) -> list[str]:
    """One example per most frequent category, with the gold and the agent's patch."""
    lines: list[str] = []
    by_category = Counter(lab["category"] for lab in labels)
    for category, _ in by_category.most_common(limit):
        lab = next(item for item in labels if item["category"] == category)
        trajectory = load_trajectory(lab["experiment"], lab["run_id"], results_dir)
        gold_patch, _ = gold_for(lab["benchmark"], lab["instance_id"])
        patch = trajectory["result"].get("final_patch") or "(no patch was produced)"
        localized = ", ".join(trajectory["result"].get("localized_files", []))
        lines += [
            f"### {DESCRIPTIONS[category]}: "
            f"`{lab['benchmark']}/{lab['instance_id']}` ({lab['experiment']})",
            "",
            f"*Classifier ({lab['source']}):* {lab['reason']}",
            "",
            f"*Localized files:* {localized or '-'}",
            "",
            "Developers' fix:",
            "```diff",
            gold_patch.strip()[:1500],
            "```",
            "Agent's final patch:",
            "```diff",
            patch.strip()[:1500],
            "```",
            "",
        ]
    return lines


def sample_for_labelling(
    labels: list[dict[str, Any]], n: int = 30, seed: int = 42
) -> list[dict[str, Any]]:
    """Seeded random sample of failures for manual labelling."""
    pool = sorted(labels, key=lambda lab: (lab["experiment"], lab["benchmark"], lab["instance_id"]))
    return random.Random(seed).sample(pool, min(n, len(pool)))


def describe_for_labelling(lab: dict[str, Any], results_dir: Path = RESULTS) -> str:
    """Everything a person needs to label a failure, WITHOUT the classifier's answer."""
    trajectory = load_trajectory(lab["experiment"], lab["run_id"], results_dir)
    gold_patch, gold_files = gold_for(lab["benchmark"], lab["instance_id"])
    result = trajectory["result"]
    problem = "\n".join(problem_text(trajectory).splitlines()[:15])
    patch = "\n".join((result.get("final_patch") or "(no patch)").splitlines()[:60])
    tests = "\n".join(last_tests(trajectory).splitlines()[:20])
    return (
        f"=== {lab['experiment']} / {lab['benchmark']} / {lab['instance_id']} ===\n"
        f"Bug report:\n{problem}\n\nGold files: {gold_files}\n"
        f"Localized files: {result.get('localized_files')}\n"
        f"Attempts used: {result.get('attempts_used')}\n"
        f"Error: {result.get('error')}\n\nDevelopers' fix:\n{gold_patch[:2500]}\n\n"
        f"Agent's final patch:\n{patch}\n\nLast test run:\n{tests}\n"
    )


def agreement(classifier: list[dict[str, Any]], manual: list[dict[str, Any]]) -> dict[str, Any]:
    by_run = {lab["run_id"]: lab["category"] for lab in classifier}
    pairs = [(by_run[m["run_id"]], m["category"]) for m in manual if m["run_id"] in by_run]
    if not pairs:
        return {"n": 0, "status": "TODO: no manual labels yet (run scripts/label_failures.py)"}
    auto, human = [p[0] for p in pairs], [p[1] for p in pairs]
    confusion: dict[str, dict[str, int]] = {}
    for a, h in pairs:
        confusion.setdefault(h, {}).setdefault(a, 0)
        confusion[h][a] += 1
    return {
        "n": len(pairs),
        "accuracy": round(sum(a == h for a, h in pairs) / len(pairs), 4),
        "cohen_kappa": round(cohen_kappa(auto, human), 4),
        "confusion_manual_to_classifier": confusion,
    }


def to_classification(lab: dict[str, Any]) -> Classification:
    keys = ("instance_id", "run_id", "category", "reason", "source", "evidence")
    return Classification(**{k: lab[k] for k in keys})
