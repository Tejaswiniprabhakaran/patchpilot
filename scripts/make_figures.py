"""Generate every report figure directly from results/ (A4).

Usage:
    python scripts/make_figures.py [--out report/figures]

Each figure is drawn only if its source data exists; otherwise the script says which results are
missing. Figures follow one visual system: thin rounded-top bars, 2 px lines, hairline grids,
text in ink colours (never the series colour), a legend only for two or more series, colours that
follow the entity (a method keeps its colour in every chart), one y-axis per chart.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.axes import Axes
from matplotlib.patches import FancyBboxPatch, Rectangle

from patchpilot.evaluation.summary import build_tables

RESULTS = Path("results")

# Reference palette (dataviz skill, light print surface); validated all-pairs for slots 1-3.
SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
BASELINE = "#c3c2b7"
SLOTS = ["#2a78d6", "#eb6834", "#1baf7a"]
# Colour follows the entity: every method/series keeps its slot in every chart.
METHOD_COLOUR = {"bm25": SLOTS[0], "embedding": SLOTS[1], "cross_encoder": SLOTS[2]}
METHOD_LABEL = {"bm25": "BM25", "embedding": "Embedding (FAISS)", "cross_encoder": "Trained ranker"}
SERIES_COLOUR = {
    "quixbugs": SLOTS[0],
    "swebench-lite": SLOTS[1],
    "train": SLOTS[0],
    "validation": SLOTS[1],
}
BENCH_LABEL = {"quixbugs": "QuixBugs", "swebench-lite": "SWE-bench Lite subset"}
CORNER_PX = 4


def style() -> None:
    plt.rcParams.update(
        {
            "font.family": ["Segoe UI", "DejaVu Sans", "sans-serif"],
            "font.size": 10,
            "figure.facecolor": SURFACE,
            "axes.facecolor": SURFACE,
            "axes.edgecolor": BASELINE,
            "axes.labelcolor": INK_2,
            "axes.titlecolor": INK,
            "axes.titlesize": 11,
            "axes.titleweight": "bold",
            "axes.axisbelow": True,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.grid": True,
            "grid.color": GRID,
            "grid.linewidth": 0.8,
            "grid.linestyle": "-",
            "xtick.color": MUTED,
            "ytick.color": MUTED,
            "xtick.labelcolor": INK_2,
            "ytick.labelcolor": INK_2,
            "legend.frameon": False,
            "legend.labelcolor": INK_2,
            "savefig.facecolor": SURFACE,
            "savefig.dpi": 200,
        }
    )


def px_to_data(ax: Axes) -> tuple[float, float]:
    """Data units per display pixel along x and y (limits must already be set)."""
    ax.figure.canvas.draw()
    bbox = ax.get_window_extent()
    (x0, x1), (y0, y1) = ax.get_xlim(), ax.get_ylim()
    return (x1 - x0) / bbox.width, (y1 - y0) / bbox.height


def capped_width(ax: Axes, slot: float, horizontal: bool = False, max_px: float = 24) -> float:
    """Bar thickness in data units: the slot share, but never more than ``max_px`` pixels."""
    dx, dy = px_to_data(ax)
    return min(slot, max_px * (dy if horizontal else dx))


def rounded_bar(
    ax: Axes,
    x: float,
    base: float,
    width: float,
    length: float,
    colour: str,
    horizontal: bool = False,
) -> None:
    """A bar with a 4 px rounded data end and a square baseline end.

    FancyBboxPatch measures its corner radius in x data units and squashes y by
    ``mutation_aspect``; using dy/dx makes the corners circular on screen in either orientation.
    """
    if length <= 0:
        return
    dx, dy = px_to_data(ax)
    radius_along = min(CORNER_PX * (dx if horizontal else dy), length / 2)
    if horizontal:
        left, bottom, w, h = base, x - width / 2, length, width
        square = Rectangle((left, bottom), max(length - radius_along, 0), h, color=colour, lw=0)
    else:
        left, bottom, w, h = x - width / 2, base, width, length
        square = Rectangle((left, bottom), w, max(length - radius_along, 0), color=colour, lw=0)
    patch = FancyBboxPatch(
        (left, bottom),
        w,
        h,
        boxstyle=f"round,pad=0,rounding_size={CORNER_PX * dx}",
        mutation_aspect=dy / dx,
        color=colour,
        lw=0,
    )
    ax.add_patch(patch)
    ax.add_patch(square)


def compact(value: float, _pos: object = None) -> str:
    """Tick labels: 0, 500, 1K, 2K ... (compact from 1,000 up)."""
    return f"{value / 1000:g}K" if abs(value) >= 1000 else f"{value:g}"


def save(fig: Any, out: Path, name: str, source: str) -> Path:
    fig.text(0.01, 0.01, f"Source: {source}", color=MUTED, fontsize=7.5, ha="left", va="bottom")
    path = out / f"{name}.png"
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    print(f"wrote {path}  (from {source})")
    return path


# ---------------------------------------------------------------------- figures


def fig_localization_topk(out: Path) -> Path | None:
    """Top-k accuracy on the held-out test repositories, per method; files and functions."""
    files = sorted(RESULTS.glob("localization/heldout_*_test.json"))
    runs = [json.loads(p.read_text(encoding="utf-8")) for p in files]
    runs = [r for r in runs if r["method"] in METHOD_COLOUR]
    if not runs:
        print("skip localization_topk: no results/localization/heldout_*_test.json yet")
        return None
    runs.sort(key=lambda r: list(METHOD_COLOUR).index(r["method"]))
    ks = ["top1", "top3", "top5"]
    fig, axes = plt.subplots(1, 2, figsize=(8.2, 3.4), sharey=True)
    width = 0.8 / len(runs)
    for ax, level, title in zip(
        axes, ["file_level", "function_level"], ["File level", "Function level"], strict=True
    ):
        ax.set_xlim(-0.6, len(ks) - 0.4)
        ax.set_ylim(0, 1.08)
        ax.set_title(f"{title} (n={runs[0][level]['n']:,})", loc="left")
        ax.set_xticks(range(len(ks)), ["Top-1", "Top-3", "Top-5"])
        ax.grid(axis="x", visible=False)
        ax.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0, decimals=0))
        bar = capped_width(ax, width * 0.86)
        for i, run in enumerate(runs):
            for j, k in enumerate(ks):
                value = run[level][k]
                x = j + (i - (len(runs) - 1) / 2) * (bar + 2 * px_to_data(ax)[0])  # 2px surface gap
                rounded_bar(ax, x, 0, bar, value, METHOD_COLOUR[run["method"]])
                ax.text(
                    x,
                    value + 0.02,
                    f"{value:.0%}",
                    ha="center",
                    va="bottom",
                    color=INK_2,
                    fontsize=8,
                )
    if len(runs) > 1:
        handles = [Rectangle((0, 0), 1, 1, color=METHOD_COLOUR[r["method"]]) for r in runs]
        fig.legend(
            handles, [METHOD_LABEL[r["method"]] for r in runs], loc="upper right", ncols=len(runs)
        )
    fig.suptitle(
        "Fault localization on held-out repositories"
        + ("" if len(runs) > 1 else f": {METHOD_LABEL[runs[0]['method']]}"),
        x=0.01,
        ha="left",
        color=INK,
        fontsize=12,
        fontweight="bold",
    )
    fig.tight_layout(rect=(0, 0.04, 1, 0.95))
    return save(fig, out, "localization_topk", ", ".join(str(p).replace("\\", "/") for p in files))


def fig_resolve_rates(out: Path) -> Path | None:
    """Resolve rate (dot) and its 95% Wilson interval (line) per configuration."""
    rows = [r for r in build_tables()["resolve_rates"] if r["n"]]
    if not rows:
        print("skip resolve_rates: no experiment results yet")
        return None
    benchmarks = [b for b in BENCH_LABEL if any(r["benchmark"] == b for r in rows)]
    heights = [len([r for r in rows if r["benchmark"] == b]) for b in benchmarks]
    fig, axes = plt.subplots(
        len(benchmarks),
        1,
        figsize=(7.5, 1.1 + sum(0.45 * h + 0.6 for h in heights)),
        squeeze=False,
        gridspec_kw={"height_ratios": heights},
    )
    for ax, benchmark in zip(axes[:, 0], benchmarks, strict=True):
        part = [r for r in rows if r["benchmark"] == benchmark]
        ax.set_xlim(0, 1.0)
        ax.set_ylim(len(part) - 0.5, -0.5)
        ax.set_yticks(range(len(part)), [r["config"] for r in part])
        ax.grid(axis="y", visible=False)
        ax.xaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0, decimals=0))
        ax.set_title(BENCH_LABEL[benchmark], loc="left")
        for i, r in enumerate(part):
            ax.plot(
                [r["ci95_low"], r["ci95_high"]],
                [i, i],
                color=SLOTS[0],
                lw=2,
                solid_capstyle="round",
            )
            ax.scatter(
                [r["rate"]], [i], s=64, color=SLOTS[0], edgecolors=SURFACE, linewidths=2, zorder=3
            )
            note = "" if r["status"] == "complete" else "  (incomplete)"
            ax.text(
                min(r["ci95_high"] + 0.02, 0.78),
                i,
                f"{r['resolved']}/{r['n']} = {r['rate']:.0%}{note}",
                va="center",
                color=INK_2,
                fontsize=8.5,
            )
    fig.suptitle(
        "Resolve rate (dot) with 95% Wilson interval (line)",
        x=0.01,
        ha="left",
        color=INK,
        fontsize=12,
        fontweight="bold",
    )
    fig.tight_layout(rect=(0, 0.06, 1, 0.92))
    return save(
        fig, out, "resolve_rates", "results/summary (from results/<experiment>/<benchmark>.jsonl)"
    )


def fig_retries_curve(out: Path) -> Path | None:
    curve = build_tables()["retries_curve"]
    if not curve:
        print("skip retries_curve: needs E3 results (TODO: not yet run)")
        return None
    fig, ax = plt.subplots(figsize=(6.2, 3.4))
    benchmarks = [b for b in BENCH_LABEL if any(c["benchmark"] == b for c in curve)]
    for benchmark in benchmarks:
        part = [c for c in curve if c["benchmark"] == benchmark]
        xs, ys = [c["attempts"] for c in part], [c["rate"] for c in part]
        colour = SERIES_COLOUR[benchmark]
        ax.plot(xs, ys, color=colour, lw=2, solid_joinstyle="round", solid_capstyle="round")
        ax.scatter(xs, ys, s=36, color=colour, edgecolors=SURFACE, linewidths=2, zorder=3)
        ax.annotate(
            f"{BENCH_LABEL[benchmark]} {ys[-1]:.0%}",
            (xs[-1], ys[-1]),
            xytext=(6, 0),
            textcoords="offset points",
            va="center",
            color=INK_2,
            fontsize=8.5,
        )
    ax.set_xticks([1, 2, 3, 5])
    ax.set_xlabel("maximum attempts")
    ax.set_ylim(0, 1)
    ax.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0, decimals=0))
    if len(benchmarks) > 1:
        ax.legend([BENCH_LABEL[b] for b in benchmarks], loc="lower right")
    ax.set_title("Resolved within k attempts (E3)", loc="left")
    fig.tight_layout(rect=(0, 0.05, 1, 1))
    return save(fig, out, "retries_curve", "results/E3/<benchmark>.jsonl")


def fig_llm_speed(out: Path) -> Path | None:
    path = RESULTS / "llm_speed_cpu.jsonl"
    if not path.exists():
        print("skip llm_speed: no results/llm_speed_cpu.jsonl")
        return None
    rows = sorted(
        (json.loads(line) for line in path.read_text().splitlines() if line),
        key=lambda r: r["prompt_tokens"],
    )
    fig, axes = plt.subplots(1, 2, figsize=(8.2, 3.2))
    panels = [("prompt_tok_per_s", "Prompt processing"), ("gen_tok_per_s", "Generation")]
    for ax, (key, title) in zip(axes, panels, strict=True):
        xs, ys = [r["prompt_tokens"] for r in rows], [r[key] for r in rows]
        ax.plot(xs, ys, color=SLOTS[0], lw=2, solid_joinstyle="round")
        ax.scatter(xs, ys, s=36, color=SLOTS[0], edgecolors=SURFACE, linewidths=2, zorder=3)
        ax.annotate(
            f"{ys[-1]:.1f} tokens/s",
            (xs[-1], ys[-1]),
            xytext=(-4, 8),
            textcoords="offset points",
            ha="right",
            color=INK_2,
            fontsize=8.5,
        )
        ax.set_title(f"{title} (tokens/s)", loc="left")
        ax.set_xlabel("prompt length (tokens)")
        ax.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(compact))
        ax.set_ylim(0, max(ys) * 1.25)
    fig.suptitle(
        f"{rows[0]['model']} on the laptop CPU (Ollama)",
        x=0.01,
        ha="left",
        color=INK,
        fontsize=12,
        fontweight="bold",
    )
    fig.tight_layout(rect=(0, 0.05, 1, 0.93))
    return save(fig, out, "llm_speed_cpu", str(path).replace("\\", "/"))


def fig_training_loss(out: Path, name: str, path: Path, title: str) -> Path | None:
    """Loss curves from a training log downloaded from the Hub (results/training/*.json)."""
    if not path.exists():
        print(f"skip {name}: {path} not present (TODO: training not yet run)")
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    history: Sequence[dict[str, Any]] = data["log_history"] if isinstance(data, dict) else data
    series = {
        "train": [(h["step"], h["loss"]) for h in history if "loss" in h],
        "validation": [(h["step"], h["eval_loss"]) for h in history if "eval_loss" in h],
    }
    series = {k: v for k, v in series.items() if v}
    fig, ax = plt.subplots(figsize=(6.2, 3.4))
    for label, points in series.items():
        xs, ys = zip(*points, strict=True)
        ax.plot(xs, ys, color=SERIES_COLOUR[label], lw=2, solid_joinstyle="round")
        ax.annotate(
            f"{label} {ys[-1]:.3f}",
            (xs[-1], ys[-1]),
            xytext=(6, 0),
            textcoords="offset points",
            va="center",
            color=INK_2,
            fontsize=8.5,
        )
    if len(series) > 1:
        ax.legend(list(series), loc="upper right")
    ax.set_xlabel("optimizer step")
    ax.set_ylabel("loss")
    ax.set_title(title, loc="left")
    fig.tight_layout(rect=(0, 0.05, 1, 1))
    return save(fig, out, name, str(path).replace("\\", "/"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("report/figures"))
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    style()
    fig_localization_topk(args.out)
    fig_resolve_rates(args.out)
    fig_retries_curve(args.out)
    fig_llm_speed(args.out)
    fig_training_loss(
        args.out,
        "loss_fault_localization",
        RESULTS / "training/fault_localization_log.json",
        "Cross-encoder fine-tuning loss",
    )
    fig_training_loss(
        args.out,
        "loss_patch_generator",
        RESULTS / "training/patch_generator_log.json",
        "Gemma 4 E4B QLoRA loss",
    )


if __name__ == "__main__":
    main()
