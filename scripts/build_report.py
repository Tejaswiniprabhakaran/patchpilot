"""Build the project report (Issue #17): refresh its generated sections from results/, then write
the DOCX and the PDF.

report/report.md is the source. Every number that comes from an experiment sits between
`<!-- BEGIN generated:NAME -->` and `<!-- END generated:NAME -->` and is rewritten here from the
files in results/; results that do not exist yet are written as "TODO: not yet run". The Markdown,
the DOCX and the PDF therefore always agree with the data they cite.

Usage:
    python scripts/build_report.py              # refresh report.md, write the DOCX and the PDF
    python scripts/build_report.py --no-pdf     # without Microsoft Word: skip the PDF
Writes report/PatchPilot_report.docx and .pdf. Needs python-docx (pip install -e ".[report]");
Microsoft Word fills in the table of contents and prints the PDF.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import sys
from collections.abc import Callable, Iterator
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from patchpilot.evaluation.stats import paired_compare

REPORT = Path("report/report.md")
DOCX = Path("report/PatchPilot_report.docx")
PDF = Path("report/PatchPilot_report.pdf")
RESULTS = Path("results")
LOC = RESULTS / "localization"
TODO = "TODO: not yet run"
BENCH = {"quixbugs": "QuixBugs", "swebench-lite": "SWE-bench Lite subset"}
METHODS = {"bm25": "BM25", "embedding": "Embeddings (FAISS)", "cross_encoder": "Trained ranker"}


# ---------------------------------------------------------------------- reading results


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def load_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def pct(value: Any) -> str:
    return "-" if value in (None, "") else f"{float(value):.1%}"


def md_table(header: list[str], rows: list[list[Any]]) -> str:
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(str(cell) for cell in row) + " |" for row in rows]
    return "\n".join(lines)


def source(*paths: Path | str) -> str:
    names = ", ".join("`" + str(p).replace("\\", "/") + "`" for p in paths)
    return f"Source: {names}."


def figure(path: str, caption: str) -> str:
    return f"\n\n![{caption}]({path})" if (REPORT.parent / path).exists() else ""


def resolve_rates() -> dict[tuple[str, str], dict[str, str]]:
    rows = load_csv(RESULTS / "summary/resolve_rates.csv")
    return {(r["config"], r["benchmark"]): r for r in rows}


def paired_tests() -> list[dict[str, str]]:
    return load_csv(RESULTS / "summary/paired_tests.csv")


def rate_text(row: dict[str, str] | None, interval: bool = True) -> str | None:
    if not row or not row.get("n"):
        return None
    text = f"{row['resolved']}/{row['n']} ({pct(row['rate'])}"
    if interval:
        text += f", 95% CI {pct(row['ci95_low'])} to {pct(row['ci95_high'])}"
    return text + ("" if row["status"] == "complete" else "; run still in progress") + ")"


def done_test(a: str, b: str, benchmark: str) -> dict[str, str] | None:
    for test in paired_tests():
        if (test["a"], test["b"], test["benchmark"]) == (a, b, benchmark):
            return test if test["status"] == "done" else None
    return None


def heldout_sample() -> tuple[int | None, dict[str, dict[str, Any]]]:
    """Metrics per method on the largest seeded held-out sample evaluated so far."""
    found: dict[int, dict[str, dict[str, Any]]] = {}
    for path in LOC.glob("heldout_*_test_sample*.json"):
        metrics = load_json(path)
        size = int(re.search(r"_sample(\d+)\.json$", path.name).group(1))  # type: ignore[union-attr]
        found.setdefault(size, {})[metrics["method"]] = metrics
    if not found:
        return None, {}
    size = max(found, key=lambda s: (len(found[s]), s))
    return size, found[size]


# ---------------------------------------------------------------------- generated sections


def gen_abstract() -> str:
    rates = resolve_rates()

    def on_both(config: str) -> str | None:
        parts = [
            f"{text} on the {BENCH[b]}" if b == "swebench-lite" else f"{text} on {BENCH[b]}"
            for b in BENCH
            if (text := rate_text(rates.get((config, b)), interval=False))
        ]
        return " and ".join(parts) or None

    sentences = []
    b0, e1 = on_both("B0"), on_both("E1")
    sentences.append(
        f"With base Gemma 4 E4B on a laptop CPU, the baseline (B0, LLM-search localization) "
        f"resolved {b0}."
        if b0
        else f"Baseline resolve rates: {TODO}."
    )
    if e1:
        tests = [
            f"p = {t['mcnemar_exact_p']} on {BENCH[b]}"
            for b in BENCH
            if (t := done_test("B0", "E1", b))
        ]
        paired = f" (exact McNemar test against B0: {'; '.join(tests)})" if tests else ""
        sentences.append(f"With the trained ranker (E1) it resolved {e1}{paired}.")
    else:
        sentences.append(f"Resolve rates with the trained ranker (E1): {TODO}.")
    first, full = rates.get(("B0@1", "quixbugs")), rates.get(("B0", "quixbugs"))
    if first and first.get("n") and full and full.get("n"):
        sentences.append(
            "Retries with test feedback raised B0 on QuixBugs from "
            f"{first['resolved']}/{first['n']} at the first attempt to "
            f"{full['resolved']}/{full['n']}."
        )
    size, sample = heldout_sample()
    if size and "cross_encoder" in sample:
        others = ", ".join(
            f"{METHODS[m]} {pct(sample[m]['function_level']['top1'])}"
            for m in ("bm25", "embedding")
            if m in sample
        )
        sentences.append(
            f"On a seeded sample of {size} held-out instances from repositories never seen in "
            f"training, the trained ranker placed the buggy function first in "
            f"{pct(sample['cross_encoder']['function_level']['top1'])} of cases ({others})."
        )
    else:
        sentences.append(f"Fault-localization accuracy of the trained ranker: {TODO}.")
    sentences.append(
        "Fine-tuning the patch generator was dropped (decision D18): the base model already "
        "fixes bugs and no GPU was available; its training data and notebook remain in the "
        "repository."
    )
    return "**Results.** " + " ".join(sentences)


def gen_training() -> str:
    log = load_json(RESULTS / "training/fault_localization_log.json")
    if not log:
        return f"CPU training run of the ranker (D16): {TODO}."
    cfg = log["config"]
    losses = [h["loss"] for h in log["log_history"] if "loss" in h]
    rows = [
        ["Base model", f"`{cfg.get('base_model', 'microsoft/unixcoder-base')}`"],
        ["Training instances (seeded sample)", f"{log['instances_sampled']:,} of 6,329"],
        [
            "Pairs available / used",
            f"{log['pairs_available']:,} / {log['pairs_seen']:,} "
            f"({log['positive_share']:.1%} of available pairs positive)",
        ],
        ["Optimizer steps", f"{log['steps']:,} of batch {cfg['batch']}"],
        ["Sequence length", f"{cfg['max_len']} tokens (bug report: {cfg['query_tokens']})"],
        ["Learning rate", f"{cfg['lr']} (linear decay, 6% warm-up), seed {cfg['seed']}"],
        [
            "Time budget / speed probe",
            f"{cfg['budget_hours']} h / "
            + (
                f"{log['probe_seconds_per_step']} s per step"
                if log["probe_seconds_per_step"]
                else "-"
            ),
        ],
        [
            "Training time",
            f"{log['train_seconds'] / 3600:.2f} h ({log['torch_threads']} CPU threads)",
        ],
    ]
    if losses:
        rows.append(["Training loss (first / last logged)", f"{losses[0]:.3f} / {losses[-1]:.3f}"])
    text = md_table(["Item", "Value"], rows)
    text += "\n\n" + source("results/training/fault_localization_log.json")
    return text + figure(
        "figures/loss_fault_localization.png",
        "Training loss of the fault-localization cross-encoder (CPU recipe, D16)",
    )


def loc_row(label: str, metrics: dict[str, Any]) -> list[str]:
    files, funcs = metrics["file_level"], metrics["function_level"]
    return [
        label,
        pct(files.get("top1")),
        pct(files.get("top5")),
        pct(funcs.get("top1")),
        pct(funcs.get("top3")),
        pct(funcs.get("top5")),
        f"{funcs['mrr']:.3f}" if funcs.get("n") else "-",
    ]


def top1_hits(path: Path, key: str) -> dict[str, bool]:
    return {r["instance_id"]: r[key] == 1 for r in load_jsonl(path) if r.get(key) is not None}


def gen_localization() -> str:
    header = ["Method", "File Top-1", "File Top-5", "Func. Top-1", "Func. Top-3", "Func. Top-5"]
    header.append("Func. MRR")
    parts = []
    size, sample = heldout_sample()
    if size:
        rows = [loc_row(METHODS[m], sample[m]) for m in METHODS if m in sample]
        any_metrics = next(iter(sample.values()))
        parts.append(
            f"**Held-out repositories, seeded sample of {size} test instances** (every method on "
            f"the same instances; {any_metrics['file_level']['n']} with a gold file, "
            f"{any_metrics['function_level']['n']} with a gold function):\n\n"
            + md_table(header, rows)
        )
        if "cross_encoder" in sample and "bm25" in sample:
            notes = []
            for level, key in (("file", "file_rank"), ("function", "unit_rank")):
                stems = {m: LOC / f"heldout_{m}_test_sample{size}.jsonl" for m in METHODS}
                cmp = paired_compare(
                    "BM25",
                    top1_hits(stems["bm25"], key),
                    "ranker",
                    top1_hits(stems["cross_encoder"], key),
                )
                notes.append(
                    f"{level} level: first only for BM25 {cmp.a_only}, only for the ranker "
                    f"{cmp.b_only}, exact McNemar p = {cmp.p_value:.4f}"
                )
            parts.append(
                "Paired Top-1 comparison, trained ranker vs BM25: " + "; ".join(notes) + "."
            )
        parts.append(source(*sorted(str(p) for p in LOC.glob(f"heldout_*_test_sample{size}.json"))))
    else:
        parts.append(f"Held-out comparison of BM25, embeddings and the trained ranker: {TODO}.")
    full = load_json(LOC / "heldout_bm25_test.json")
    if full:
        parts.append(
            f"**All {full['file_level']['n']:,} held-out test instances, BM25 only** "
            f"(reference for the sample above):\n\n" + md_table(header, [loc_row("BM25", full)])
        )
        parts.append(source(LOC / "heldout_bm25_test.json"))
    swe = {m: load_json(LOC / f"swebench_{m}.json") for m in METHODS}
    swe = {m: v for m, v in swe.items() if v}
    if swe:
        rows = [
            [
                METHODS[m],
                pct(v["file_level"]["top1"]),
                pct(v["file_level"]["top3"]),
                pct(v["file_level"]["top5"]),
                pct(v["function_level"]["top1"]),
                pct(v["function_level"]["top5"]),
            ]
            for m, v in swe.items()
        ]
        n = next(iter(swe.values()))["file_level"]["n"]
        parts.append(
            f"**SWE-bench Lite evaluation subset, whole repository** ({n} instances; BM25 over "
            f"every Python file, re-ranking of its top 50; functions of the top-3 files):\n\n"
            + md_table(
                ["Method", "File Top-1", "File Top-3", "File Top-5", "Func. Top-1", "Func. Top-5"],
                rows,
            )
        )
        parts.append(source(*sorted(f"results/localization/swebench_{m}.json" for m in swe)))
    else:
        parts.append(f"Whole-repository localization on the SWE-bench subset: {TODO}.")
    return "\n\n".join(parts) + figure(
        "figures/localization_topk.png",
        "Top-k fault-localization accuracy on held-out repositories",
    )


def gen_resolve() -> str:
    csv_rows = load_csv(RESULTS / "summary/resolve_rates.csv")
    if not csv_rows:
        return f"Resolve rates: {TODO}."
    rates = resolve_rates()
    configs = list(dict.fromkeys(r["config"] for r in csv_rows))
    describe = {r["config"]: r["description"] for r in csv_rows}
    rows = []
    for config in configs:
        cells = []
        for benchmark in BENCH:
            row = rates.get((config, benchmark))
            cells.append(rate_text(row) or (row["status"] if row else TODO))
        rows.append([config, describe[config], *cells])
    parts = [md_table(["Config", "Description", BENCH["quixbugs"], BENCH["swebench-lite"]], rows)]
    excluded = sorted({x for r in csv_rows for x in r["excluded"].split() if x})
    if excluded:
        parts.append(
            "Excluded from scoring because the gold patch fails in the network-off sandbox (D11): "
            + ", ".join(f"`{x}`" for x in excluded)
            + "."
        )
    parts.append(source("results/summary/resolve_rates.csv"))
    test_rows = []
    for t in paired_tests():
        if t["status"] == "done":
            cells = [f"{t['a_resolved']}/{t['n']}", f"{t['b_resolved']}/{t['n']}", t["a_only"]]
            cells += [t["b_only"], t["mcnemar_exact_p"]]
        else:
            cells = ["-", "-", "-", "-", "TODO"]
        test_rows.append([t["question"], BENCH[t["benchmark"]], f"{t['a']} vs {t['b']}", *cells])
    parts.append(
        "**Paired comparisons** (exact McNemar test on the instances both runs attempted; TODO: "
        "a run is missing or incomplete):\n\n"
        + md_table(
            [
                "Question",
                "Benchmark",
                "A vs B",
                "A resolved",
                "B resolved",
                "A only",
                "B only",
                "p",
            ],
            test_rows,
        )
    )
    parts.append(source("results/summary/paired_tests.csv"))
    return (
        "\n\n".join(parts)
        + figure(
            "figures/resolve_rates.png", "Resolve rate per configuration with 95% Wilson intervals"
        )
        + figure("figures/retries_curve.png", "Instances resolved within k attempts")
    )


def gen_cost() -> str:
    rows = load_csv(RESULTS / "summary/cost.csv")
    if not rows:
        return f"Cost per instance: {TODO}."
    table = [
        [
            r["config"],
            BENCH[r["benchmark"]],
            f"{float(r['wall_s_mean']) / 60:.1f} / {float(r['wall_s_median']) / 60:.1f}",
            f"{float(r['llm_calls_mean']):.1f}",
            f"{float(r['prompt_tokens_mean']):,.0f}",
            f"{float(r['completion_tokens_mean']):,.0f}",
            f"{float(r['attempts_used_mean']):.2f}",
            r["status"],
        ]
        for r in rows
    ]
    header = ["Config", "Benchmark", "Minutes (mean / median)", "Model calls", "Prompt tokens"]
    header += ["Output tokens", "Attempts", "Status"]
    return md_table(header, table) + "\n\n" + source("results/summary/cost.csv")


def gen_requeued() -> str:
    parts = []
    for path in sorted(RESULTS.glob("*/infra_failures.jsonl")):
        experiment = path.parent.name
        rows = []
        for old in load_jsonl(path):
            current = {
                r["instance_id"]: r
                for r in load_jsonl(RESULTS / experiment / f"{old['benchmark']}.jsonl")
            }.get(old["instance_id"])
            rerun = (
                TODO if current is None else ("resolved" if current["resolved"] else "not resolved")
            )
            first = "resolved" if old["resolved"] else "not resolved"
            rows.append([experiment, old["instance_id"], old["requeue_reason"], first, rerun])
        parts.append(
            md_table(["Experiment", "Instance", "Reason (fixed rule)", "First run", "Re-run"], rows)
        )
        parts.append(source(path, f"results/{experiment}/<benchmark>.jsonl"))
    return "\n\n".join(parts) or "No run was re-queued."


def gen_failures() -> str:
    rows = load_csv(RESULTS / "analysis/taxonomy.csv")
    if not rows:
        return f"Failure taxonomy: {TODO}."
    table = [
        [
            r["experiment"],
            BENCH.get(r["benchmark"], r["benchmark"]),
            r["category"].replace("_", " "),
            r["description"],
            f"{r['count']} of {r['failed_runs']}",
            pct(r["share"]),
        ]
        for r in rows
    ]
    parts = [
        md_table(["Experiment", "Benchmark", "Category", "Meaning", "Runs", "Share"], table),
        source("results/analysis/taxonomy.csv", "results/analysis/failure_labels.jsonl"),
    ]
    agreement = load_json(RESULTS / "analysis/agreement.json") or {}
    if agreement.get("n"):
        parts.append(
            f"Agreement of the automatic labels with {agreement['n']} blind manual labels: "
            f"Cohen's kappa = {agreement.get('kappa')} (`results/analysis/agreement.json`)."
        )
    else:
        parts.append(
            "Agreement with manual labels: TODO: the blind labelling tool "
            "(`scripts/label_failures.py`) needs a person."
        )
    return "\n\n".join(parts)


def gen_answers() -> str:
    rates = resolve_rates()
    lines = []

    def compare(a: str, b: str, what: str) -> list[str]:
        out = []
        for benchmark in BENCH:
            t = done_test(a, b, benchmark)
            if t is None:
                out.append(f"{BENCH[benchmark]}: {TODO} (needs complete {a} and {b} runs).")
                continue
            verdict = "is" if t["significant_at_0.05"] == "True" else "is not"
            out.append(
                f"{BENCH[benchmark]}: {b} resolved {t['b_resolved']}/{t['n']} and {a} "
                f"{t['a_resolved']}/{t['n']}; {t['b_only']} only with {what}, {t['a_only']} only "
                f"without; exact McNemar p = {t['mcnemar_exact_p']}, so the difference {verdict} "
                f"statistically significant at the 0.05 level."
            )
        return out

    fixed = [
        f"{config} {text} on {BENCH[b]}"
        for config in ("B0", "E1")
        for b in BENCH
        if (text := rate_text(rates.get((config, b))))
    ]
    lines.append(
        "- **RQ1 (how many real bugs can an open-weight agent fix?)** With base Gemma 4 E4B on a "
        "laptop CPU: " + ("; ".join(fixed) if fixed else TODO) + "."
    )
    lines.append("- **RQ2 (does the trained ranker help?)** " + " ".join(compare("B0", "E1", "E1")))
    size, sample = heldout_sample()
    if size and "cross_encoder" in sample and "bm25" in sample:
        lines[-1] += (
            f" In isolation, on {size} held-out instances, the ranker's function-level Top-1 was "
            f"{pct(sample['cross_encoder']['function_level']['top1'])} against "
            f"{pct(sample['bm25']['function_level']['top1'])} for BM25 (Section 7.3)."
        )
    lines.append(
        "- **RQ3 (does fine-tuning help?)** Not studied: fine-tuning was dropped (D18), because "
        "the base model already fixes bugs and no GPU was available."
    )
    rq4 = compare("B0@1", "B0", "retries") + compare("E1@1", "E1", "retries")
    lines.append("- **RQ4 (do retries with test feedback help?)** " + " ".join(rq4))
    taxonomy = load_csv(RESULTS / "analysis/taxonomy.csv")
    if taxonomy:
        top: dict[tuple[str, str], dict[str, str]] = {}
        for r in taxonomy:
            key = (r["experiment"], r["benchmark"])
            if key not in top or int(r["count"]) > int(top[key]["count"]):
                top[key] = r
        found = "; ".join(
            f"{e} on {BENCH.get(b, b)}: {r['category'].replace('_', ' ')} "
            f"({r['count']} of {r['failed_runs']} failed runs)"
            for (e, b), r in top.items()
        )
        lines.append(f"- **RQ5 (why does the agent fail?)** Most common category: {found}.")
    else:
        lines.append(f"- **RQ5 (why does the agent fail?)** {TODO}.")
    missing = [c for c in ("B0", "E1") for b in BENCH if not rate_text(rates.get((c, b)))]
    if missing:
        lines.append(
            "\nAnswers marked TODO are filled in automatically when `scripts/run_pipeline.ps1` "
            "finishes and this report is rebuilt."
        )
    return "\n".join(lines)


def count_tests(marker: str) -> int | None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "-m",
            marker,
            "-p",
            "no:cacheprovider",
        ],
        capture_output=True,
        encoding="utf-8",
    )
    found = re.search(r"(\d+)(?:/\d+)? tests? collected", result.stdout)
    return int(found.group(1)) if found else None


def gen_testing() -> str:
    unit, integration = count_tests("not integration"), count_tests("integration")
    return (
        f"The suite has {unit} unit tests and {integration} integration tests (counted by pytest "
        f"when this report was built)."
    )


def gen_bot() -> str:
    record = load_json(RESULTS / "bot_demo/patchpilot-demo-pr1.json")
    if not record:
        return f"GitHub bot demonstration: {TODO}."
    body = record["comment"]["body"]
    attempts = re.search(r"attempts used: (\d+)", body)
    seconds = re.search(r"time: (\d+) s", body)
    model = re.search(r"Model: `([^`]+)`", body)
    jobs = {j["name"]: j for j in record["jobs"]}

    def minutes(job: dict[str, str]) -> str:
        seconds = date_time(job["completed_at"]) - date_time(job["started_at"])
        return f"{seconds:.0f} s" if seconds < 90 else f"{seconds / 60:.1f} min"

    pr = record["pull_request"]
    text = (
        f"The bot was tried on a public demo repository: the pull request "
        f"[{pr['title']}]({pr['url']}) introduces an off-by-one bug into a working function. "
        f"Its test job failed ({minutes(jobs['tests'])}); the PatchPilot job then ran on a "
        f"GitHub-hosted runner for {minutes(jobs['patchpilot'])} (installing Ollama and the model "
        f"included) and posted the comment shown below: a patch found with "
        f"`{model.group(1) if model else '?'}` at attempt {attempts.group(1) if attempts else '?'} "
        f"in {seconds.group(1) if seconds else '?'} s, with the test output before and after. "
        "Nothing was pushed or merged."
    )
    return (
        text
        + "\n\n"
        + source("results/bot_demo/patchpilot-demo-pr1.json")
        + figure("figures/bot_comment.png", "The bot's comment on the demo pull request")
    )


def date_time(value: str) -> float:
    from datetime import datetime

    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


GENERATORS: dict[str, Callable[[], str]] = {
    "abstract": gen_abstract,
    "training": gen_training,
    "localization": gen_localization,
    "resolve": gen_resolve,
    "cost": gen_cost,
    "requeued": gen_requeued,
    "failures": gen_failures,
    "answers": gen_answers,
    "testing": gen_testing,
    "bot": gen_bot,
}
SECTION = re.compile(
    r"(<!-- BEGIN generated:(?P<name>[\w-]+) -->\n).*?(<!-- END generated:(?P=name) -->)", re.S
)


def refresh(text: str) -> str:
    def replace(match: re.Match[str]) -> str:
        name = match.group("name")
        if name not in GENERATORS:
            raise SystemExit(f"report.md has a generated section without a generator: {name}")
        return match.group(1) + GENERATORS[name]().strip() + "\n" + match.group(3)

    return SECTION.sub(replace, text)


# ---------------------------------------------------------------------- Markdown -> DOCX

INLINE = re.compile(r"`[^`]+`|\*\*.+?\*\*|\*[^*\s](?:[^*]*?[^*\s])?\*|\[[^\]]+\]\([^)\s]+\)")
LIST_ITEM = re.compile(r"^(\s*)([-*]|\d+\.) (.*)")
CONTENT_WIDTH_CM = 16.4


def split_front_matter(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---\n"):
        return {}, text
    end = text.index("\n---\n", 4)
    return yaml.safe_load(text[4:end]) or {}, text[end + 5 :]


def blocks(text: str) -> Iterator[tuple[str, Any]]:
    lines = text.splitlines()
    i = 0

    def starts_block(line: str) -> bool:
        return bool(line.startswith(("#", "|", "```", "<!--", "![")) or LIST_ITEM.match(line))

    while i < len(lines):
        line = lines[i]
        if line.startswith("<!--"):
            while "-->" not in lines[i]:
                i += 1
            i += 1
        elif line.startswith("```"):
            j = i + 1
            while j < len(lines) and not lines[j].startswith("```"):
                j += 1
            yield "code", "\n".join(lines[i + 1 : j])
            i = j + 1
        elif heading := re.match(r"^(#{1,4}) (.*)", line):
            yield "heading", (len(heading.group(1)), heading.group(2).strip())
            i += 1
        elif line.startswith("|"):
            rows = []
            while i < len(lines) and lines[i].startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not all(re.fullmatch(r":?-+:?", c) for c in cells):
                    rows.append(cells)
                i += 1
            yield "table", rows
        elif image := re.match(r"^!\[([^\]]*)\]\(([^)]+)\)\s*$", line):
            yield "image", (image.group(1), image.group(2))
            i += 1
        elif LIST_ITEM.match(line):
            items: list[tuple[int, bool, str]] = []
            while i < len(lines) and lines[i].strip():
                item = LIST_ITEM.match(lines[i])
                if item:
                    ordered = item.group(2)[0].isdigit()
                    items.append((len(item.group(1)) // 2, ordered, item.group(3).strip()))
                elif items and lines[i].startswith(" "):
                    level, ordered, body = items[-1]
                    items[-1] = (level, ordered, body + " " + lines[i].strip())
                else:
                    break
                i += 1
            yield "list", items
        elif not line.strip():
            i += 1
        else:
            paragraph = [line.strip()]
            i += 1
            while i < len(lines) and lines[i].strip() and not starts_block(lines[i]):
                paragraph.append(lines[i].strip())
                i += 1
            yield "paragraph", " ".join(paragraph)


class DocxWriter:
    """Writes the parsed Markdown blocks into a Word document with python-docx."""

    def __init__(self, meta: dict[str, Any], built: str) -> None:
        from docx import Document
        from docx.shared import Cm, Pt, RGBColor

        self.doc = Document()
        self.figures = 0
        section = self.doc.sections[0]
        section.page_height, section.page_width = Cm(29.7), Cm(21.0)
        section.left_margin = section.right_margin = Cm(2.3)
        section.top_margin = section.bottom_margin = Cm(2.2)
        normal = self.doc.styles["Normal"]
        normal.font.name = "Calibri"
        normal.font.size = Pt(10.5)
        normal.paragraph_format.space_after = Pt(6)
        normal.paragraph_format.line_spacing = 1.12
        for name, size in (("Heading 1", 17), ("Heading 2", 13), ("Heading 3", 11.5)):
            style = self.doc.styles[name]
            style.font.name = "Calibri"
            style.font.size = Pt(size)
            style.font.color.rgb = RGBColor(0x1A, 0x2B, 0x44)
        self.title_page(meta, built)
        self.page_number_footer()

    # -- page furniture

    def title_page(self, meta: dict[str, Any], built: str) -> None:
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        from docx.shared import Pt, RGBColor

        def line(text: str, size: float, bold: bool = False, space: float = 10) -> None:
            paragraph = self.doc.add_paragraph()
            paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
            paragraph.paragraph_format.space_after = Pt(space)
            run = paragraph.add_run(text)
            run.bold, run.font.size = bold, Pt(size)
            run.font.color.rgb = RGBColor(0x1A, 0x2B, 0x44)

        for _ in range(6):
            self.doc.add_paragraph()
        line(meta.get("title", "Report"), 32, bold=True, space=14)
        line(meta.get("subtitle", ""), 14, space=36)
        line(meta.get("kind", "Technical report"), 12)
        line(meta.get("author", ""), 13, bold=True, space=36)
        line(built, 9.5)
        if meta.get("repository"):
            paragraph = self.doc.add_paragraph()
            paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
            self.hyperlink(paragraph, meta["repository"], meta["repository"])
        heading = self.doc.add_paragraph()
        heading.paragraph_format.page_break_before = True
        run = heading.add_run("Contents")
        run.bold, run.font.size = True, Pt(17)
        self.field('TOC \\o "1-2" \\h \\z \\u', "Open in Word and update fields to show contents.")

    def field(self, instruction: str, placeholder: str) -> None:
        from docx.oxml import OxmlElement
        from docx.oxml.ns import qn

        run = self.doc.add_paragraph().add_run()
        for kind, text in (("begin", None), (None, instruction), ("separate", None)):
            if kind:
                element = OxmlElement("w:fldChar")
                element.set(qn("w:fldCharType"), kind)
            else:
                element = OxmlElement("w:instrText")
                element.set(qn("xml:space"), "preserve")
                element.text = text
            run._r.append(element)
        shown = OxmlElement("w:t")
        shown.text = placeholder
        run._r.append(shown)
        end = OxmlElement("w:fldChar")
        end.set(qn("w:fldCharType"), "end")
        run._r.append(end)

    def page_number_footer(self) -> None:
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        from docx.oxml import OxmlElement
        from docx.oxml.ns import qn

        paragraph = self.doc.sections[0].footer.paragraphs[0]
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = paragraph.add_run()
        for kind, text in (("begin", None), (None, "PAGE"), ("end", None)):
            if kind:
                element = OxmlElement("w:fldChar")
                element.set(qn("w:fldCharType"), kind)
            else:
                element = OxmlElement("w:instrText")
                element.set(qn("xml:space"), "preserve")
                element.text = text
            run._r.append(element)

    # -- inline text

    def hyperlink(self, paragraph: Any, url: str, text: str) -> None:
        from docx.opc.constants import RELATIONSHIP_TYPE
        from docx.oxml import OxmlElement
        from docx.oxml.ns import qn

        r_id = paragraph.part.relate_to(url, RELATIONSHIP_TYPE.HYPERLINK, is_external=True)
        link = OxmlElement("w:hyperlink")
        link.set(qn("r:id"), r_id)
        run = OxmlElement("w:r")
        properties = OxmlElement("w:rPr")
        colour = OxmlElement("w:color")
        colour.set(qn("w:val"), "1F5FBF")
        underline = OxmlElement("w:u")
        underline.set(qn("w:val"), "single")
        properties.append(colour)
        properties.append(underline)
        run.append(properties)
        shown = OxmlElement("w:t")
        shown.set(qn("xml:space"), "preserve")
        shown.text = text
        run.append(shown)
        link.append(run)
        paragraph._p.append(link)

    def inline(self, paragraph: Any, text: str, bold: bool = False, italic: bool = False) -> None:
        from docx.shared import Pt

        def plain(chunk: str, code: bool = False) -> None:
            run = paragraph.add_run(chunk)
            run.bold, run.italic = bold or None, italic or None
            if code:
                run.font.name = "Consolas"
                run.font.size = Pt(9)

        position = 0
        for match in INLINE.finditer(text):
            if match.start() > position:
                plain(text[position : match.start()])
            token = match.group(0)
            if token.startswith("`"):
                plain(token[1:-1], code=True)
            elif token.startswith("**"):
                self.inline(paragraph, token[2:-2], True, italic)
            elif token.startswith("*"):
                self.inline(paragraph, token[1:-1], bold, True)
            else:
                label, url = re.match(r"\[([^\]]+)\]\(([^)\s]+)\)", token).groups()  # type: ignore[union-attr]
                if url.startswith("http"):
                    self.hyperlink(paragraph, url, label)
                else:
                    self.inline(paragraph, label, bold, italic)
            position = match.end()
        if position < len(text):
            plain(text[position:])

    # -- blocks

    def heading(self, level: int, text: str) -> None:
        paragraph = self.doc.add_heading(level=level)
        self.inline(paragraph, text)
        if level == 1:
            paragraph.paragraph_format.page_break_before = True

    def paragraph(self, text: str) -> None:
        self.inline(self.doc.add_paragraph(), text)

    def bullets(self, items: list[tuple[int, bool, str]]) -> None:
        from docx.shared import Cm

        number = 0
        for level, ordered, text in items:
            if ordered:
                number += 1
                paragraph = self.doc.add_paragraph()
                paragraph.paragraph_format.left_indent = Cm(0.9 + 0.6 * level)
                paragraph.paragraph_format.first_line_indent = Cm(-0.6)
                self.inline(paragraph, f"{number}.\t{text}")
                paragraph.paragraph_format.tab_stops.add_tab_stop(Cm(0.9 + 0.6 * level))
            else:
                style = "List Bullet" if level == 0 else "List Bullet 2"
                self.inline(self.doc.add_paragraph(style=style), text)

    def table(self, rows: list[list[str]]) -> None:
        from docx.oxml import OxmlElement
        from docx.oxml.ns import qn
        from docx.shared import Pt

        width = max(len(r) for r in rows)
        table = self.doc.add_table(rows=len(rows), cols=width)
        table.style = "Table Grid"
        for i, cells in enumerate(rows):
            for j in range(width):
                cell = table.cell(i, j)
                paragraph = cell.paragraphs[0]
                paragraph.paragraph_format.space_after = Pt(0)
                self.inline(paragraph, cells[j] if j < len(cells) else "", bold=i == 0)
                for run in paragraph.runs:
                    run.font.size = Pt(8.5)
                if i == 0:
                    shading = OxmlElement("w:shd")
                    shading.set(qn("w:val"), "clear")
                    shading.set(qn("w:fill"), "E8EBF0")
                    cell._tc.get_or_add_tcPr().append(shading)
        self.doc.add_paragraph().paragraph_format.space_after = Pt(2)

    def image(self, caption: str, path: Path) -> None:
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        from docx.shared import Cm, Pt
        from PIL import Image

        with Image.open(path) as picture:
            ratio = picture.height / picture.width
        width = min(CONTENT_WIDTH_CM, 20.5 / ratio)  # keep tall screenshots on one page
        self.doc.add_picture(str(path), width=Cm(width))
        self.doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
        self.figures += 1
        paragraph = self.doc.add_paragraph()
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = paragraph.add_run(f"Figure {self.figures}. {caption}")
        run.italic, run.font.size = True, Pt(9)

    def code(self, text: str) -> None:
        from docx.shared import Cm, Pt

        paragraph = self.doc.add_paragraph()
        paragraph.paragraph_format.left_indent = Cm(0.5)
        for k, line in enumerate(text.splitlines()):
            run = paragraph.add_run(line)
            run.font.name, run.font.size = "Consolas", Pt(8.5)
            if k < len(text.splitlines()) - 1:
                run.add_break()

    def write(self, body: str, base: Path) -> None:
        for kind, value in blocks(body):
            if kind == "heading":
                self.heading(*value)
            elif kind == "paragraph":
                self.paragraph(value)
            elif kind == "list":
                self.bullets(value)
            elif kind == "table":
                self.table(value)
            elif kind == "image":
                caption, relative = value
                self.image(caption, base / relative)
            elif kind == "code":
                self.code(value)

    def save(self, path: Path) -> None:
        self.doc.save(str(path))


def word_pdf(docx: Path, pdf: Path) -> None:
    """Update the table of contents and page numbers in Word, save, and export the PDF."""
    script = f"""
$ErrorActionPreference = 'Stop'
$word = New-Object -ComObject Word.Application
$word.Visible = $false
$word.DisplayAlerts = 0
try {{
    $doc = $word.Documents.Open('{docx.resolve()}', $false, $false)
    foreach ($toc in $doc.TablesOfContents) {{ $toc.Update() }}
    $doc.Fields.Update() | Out-Null
    $doc.Save()
    $doc.ExportAsFixedFormat('{pdf.resolve()}', 17)
    $doc.Close($false)
}} finally {{
    $word.Quit()
}}
"""
    subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        check=True,
        timeout=900,
    )


def git_commit() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], capture_output=True, encoding="utf-8"
    )
    return result.stdout.strip() or "unknown"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-pdf", action="store_true", help="skip the PDF (needs Word)")
    args = parser.parse_args()

    text = refresh(REPORT.read_text(encoding="utf-8"))
    REPORT.write_text(text, encoding="utf-8", newline="\n")
    print(f"refreshed the generated sections of {REPORT}")

    meta, body = split_front_matter(text)
    built = f"Built on {date.today():%d %B %Y} from commit {git_commit()}"
    writer = DocxWriter(meta, built)
    writer.write(body, REPORT.parent)
    writer.save(DOCX)
    print(f"wrote {DOCX}")
    if not args.no_pdf:
        word_pdf(DOCX, PDF)
        print(f"wrote {PDF}")


if __name__ == "__main__":
    main()
