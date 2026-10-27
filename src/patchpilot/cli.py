"""PatchPilot command-line interface (S3).

patchpilot fix  --benchmark quixbugs --instance gcd
patchpilot eval --config configs/exp_baseline.yaml
patchpilot show <run_id>
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table

from patchpilot import __version__

app = typer.Typer(
    name="patchpilot",
    help="An AI agent that fixes real bugs and verifies the fix in a Docker sandbox.",
    no_args_is_help=True,
)
console = Console()

RUNS_DIR = Path("runs")
RESULTS_DIR = Path("results")
DEFAULT_CONFIG = Path("configs/agent_dev.yaml")


@app.callback()
def main() -> None:
    """PatchPilot command-line interface."""


@app.command()
def version() -> None:
    """Print the installed PatchPilot version."""
    typer.echo(f"patchpilot {__version__}")


@app.command()
def fix(
    benchmark: Annotated[str, typer.Option(help="quixbugs or swebench-lite")],
    instance: Annotated[str, typer.Option(help="instance id, e.g. gcd")],
    config: Annotated[Path, typer.Option(help="experiment YAML for model/agent settings")] = (
        DEFAULT_CONFIG
    ),
    model: Annotated[str | None, typer.Option(help="override the model name")] = None,
    attempts: Annotated[int | None, typer.Option(help="override max attempts")] = None,
) -> None:
    """Run the agent on one benchmark instance and show the result."""
    from patchpilot.config import BenchmarkSelection, ExperimentConfig
    from patchpilot.evaluation.runner import load_benchmark, make_agent

    exp = ExperimentConfig.load(config)
    if model:
        exp.llm.model = model
    if attempts:
        exp.agent.max_attempts = attempts
    selection = BenchmarkSelection(name=benchmark, instances=[instance])  # type: ignore[arg-type]
    target = load_benchmark(selection)[0]

    console.print(f"[bold]Fixing[/] {benchmark}/{instance} with [cyan]{exp.llm.model}[/]")
    with console.status("agent running..."):
        if target.benchmark == "swebench-lite":
            from patchpilot.benchmarks import swebench

            with swebench.pulled_image(target.image, prune=True):  # D14: one image at a time
                trajectory = make_agent(exp).run(target, {"experiment": "fix"})
        else:
            trajectory = make_agent(exp).run(target, {"experiment": "fix"})
    path = trajectory.save(RUNS_DIR)
    _print_result(trajectory.to_dict())
    console.print(
        f"Trajectory saved to [green]{path}[/]  (view: patchpilot show {trajectory.run_id})"
    )


@app.command("eval")
def evaluate(
    config: Annotated[Path, typer.Option(help="experiment YAML, e.g. configs/exp_baseline.yaml")],
    benchmark: Annotated[str | None, typer.Option(help="run only this benchmark")] = None,
    limit: Annotated[int | None, typer.Option(help="stop after this many new instances")] = None,
) -> None:
    """Run an experiment over its benchmarks; results go to results/<experiment id>/."""
    from patchpilot.config import ExperimentConfig
    from patchpilot.evaluation.runner import run_experiment

    exp = ExperimentConfig.load(config)
    console.print(f"[bold]Experiment {exp.id}[/]: {exp.description}")

    def report(row: dict[str, Any]) -> None:
        mark = "[green]resolved[/]" if row["resolved"] else "[red]not resolved[/]"
        console.print(
            f"  {row['benchmark']}/{row['instance_id']}: {mark} "
            f"(attempts {row['attempts_used']}, {row['wall_s']} s)"
        )

    rows = run_experiment(exp, only_benchmark=benchmark, limit=limit, on_result=report)
    resolved = sum(r["resolved"] for r in rows)
    console.print(f"[bold]{resolved}/{len(rows)}[/] newly run instances resolved.")
    console.print(f"Raw results: {exp.output_dir()}")


@app.command()
def show(
    run_id: Annotated[str, typer.Argument(help="run id printed by fix/eval")],
    full: Annotated[bool, typer.Option(help="print complete step outputs")] = False,
) -> None:
    """Show a saved trajectory step by step."""
    data = load_trajectory(run_id)
    if data is None:
        console.print(f"[red]No trajectory found for {run_id}[/]")
        raise typer.Exit(1)
    table = Table(title=f"{data['benchmark']}/{data['instance_id']}  ({data['run_id']})")
    for column in ("#", "kind", "step", "ok", "secs", "details"):
        table.add_column(column)
    for step in data["steps"]:
        details = _step_details(step, full)
        table.add_row(
            str(step["index"]),
            step["kind"],
            step["name"],
            "[green]yes[/]" if step["ok"] else "[red]no[/]",
            f"{step['duration_s']:.1f}",
            details,
        )
    console.print(table)
    _print_result(data)


def load_trajectory(run_id: str) -> dict[str, Any] | None:
    plain = RUNS_DIR / f"{run_id}.json"
    if plain.exists():
        result: dict[str, Any] = json.loads(plain.read_text(encoding="utf-8"))
        return result
    for path in RESULTS_DIR.glob(f"*/trajectories/{run_id}.json.gz"):
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            loaded: dict[str, Any] = json.load(handle)
            return loaded
    return None


def _step_details(step: dict[str, Any], full: bool) -> str:
    args = {k: v for k, v in step["input"].items() if k != "prompt"}
    text = step["output"] if full else step["output"].strip().splitlines()[:3]
    body = text if isinstance(text, str) else "\n".join(text)
    prefix = f"{args}\n" if args else ""
    return (prefix + body)[: None if full else 300]


def _print_result(data: dict[str, Any]) -> None:
    result = data.get("result", {})
    status = "[bold green]RESOLVED[/]" if result.get("resolved") else "[bold red]NOT RESOLVED[/]"
    lines = [
        status,
        f"attempts used: {result.get('attempts_used')}",
        f"localized files: {', '.join(result.get('localized_files', []))}",
        f"LLM calls: {result.get('llm_calls')}, tokens in/out: "
        f"{result.get('prompt_tokens')}/{result.get('completion_tokens')}",
        f"wall time: {result.get('wall_s')} s",
    ]
    if result.get("error"):
        lines.append(f"[red]error: {result['error']}[/]")
    console.print(Panel("\n".join(lines), title="Result"))
    if result.get("final_patch"):
        console.print(Syntax(result["final_patch"], "diff", theme="ansi_dark"))
