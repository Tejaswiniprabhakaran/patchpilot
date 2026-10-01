"""Run one experiment over its benchmark instances and save raw results.

Output layout for experiment ``B0``:

    results/B0/config.yaml                     exact config used
    results/B0/<benchmark>.jsonl               one summary row per instance (resumable)
    results/B0/trajectories/<run_id>.json.gz   full trajectory of every run

Rows already present are skipped, so an interrupted run continues where it stopped.
"""

from __future__ import annotations

import gzip
import json
import subprocess
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from patchpilot.agent import Agent, LLMSearchLocalizer, Localizer, Trajectory
from patchpilot.benchmarks import BenchmarkInstance
from patchpilot.config import BenchmarkSelection, ExperimentConfig
from patchpilot.llm import LLMClient, OpenAICompatibleClient, UsageLog


def load_benchmark(selection: BenchmarkSelection) -> list[BenchmarkInstance]:
    if selection.name == "quixbugs":
        from patchpilot.benchmarks import quixbugs

        quixbugs.ensure_downloaded()
        quixbugs.build_image()
        if isinstance(selection.instances, list):
            return [quixbugs.load_instance(name) for name in selection.instances]
        return quixbugs.load_instances()
    from patchpilot.benchmarks import swebench

    if isinstance(selection.instances, list):
        return [swebench.load_instance(i) for i in selection.instances]
    if selection.instances == "subset50":
        return swebench.load_subset()
    if selection.instances == "subset10":
        return swebench.load_subset(swebench.SMALL_SUBSET_FILE)
    return swebench.load_instances()


def make_localizer(config: ExperimentConfig, llm: LLMClient) -> Localizer:
    if config.localizer == "llm_search":
        return LLMSearchLocalizer(llm, top_k=config.agent.top_k_files)
    raise NotImplementedError(f"localizer {config.localizer!r} arrives in Phase 3")


def make_agent(config: ExperimentConfig) -> Agent:
    """A fresh agent (and usage log) per instance, so token counts are per instance."""
    llm = OpenAICompatibleClient(config.llm, usage=UsageLog())
    return Agent(llm, make_localizer(config, llm), config.agent)


def summary_row(trajectory: Trajectory, config: ExperimentConfig) -> dict[str, Any]:
    r = trajectory.result
    return {
        "experiment": config.id,
        "benchmark": trajectory.benchmark,
        "instance_id": trajectory.instance_id,
        "run_id": trajectory.run_id,
        "model": config.llm.model,
        "localizer": config.localizer,
        "max_attempts": config.agent.max_attempts,
        "resolved": bool(r.get("resolved")),
        "applied": bool(r.get("applied")),
        "fail_to_pass_ok": r.get("fail_to_pass_ok"),
        "pass_to_pass_ok": r.get("pass_to_pass_ok"),
        "attempts_used": r.get("attempts_used", 0),
        "best_attempt": r.get("best_attempt"),
        "localized_files": r.get("localized_files", []),
        "llm_calls": r.get("llm_calls", 0),
        "prompt_tokens": r.get("prompt_tokens", 0),
        "completion_tokens": r.get("completion_tokens", 0),
        "wall_s": r.get("wall_s"),
        "error": r.get("error"),
        "finished_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }


def save_trajectory(trajectory: Trajectory, directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{trajectory.run_id}.json.gz"
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        json.dump(trajectory.to_dict(), handle)
    return path


def git_commit() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=False
        )
        return out.stdout.strip() or "unknown"
    except OSError:
        return "unknown"


def run_experiment(
    config: ExperimentConfig,
    only_benchmark: str | None = None,
    limit: int | None = None,
    agent_factory: Callable[[ExperimentConfig], Agent] = make_agent,
    instances_override: dict[str, list[BenchmarkInstance]] | None = None,
    on_result: Callable[[dict[str, Any]], None] | None = None,
) -> list[dict[str, Any]]:
    out_dir = config.output_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "config.yaml").write_text(
        yaml.safe_dump(config.model_dump(mode="json"), sort_keys=False), encoding="utf-8"
    )
    rows: list[dict[str, Any]] = []
    for selection in config.benchmarks:
        if only_benchmark and selection.name != only_benchmark:
            continue
        results_file = out_dir / f"{selection.name}.jsonl"
        done = _done_ids(results_file)
        instances = (instances_override or {}).get(selection.name) or load_benchmark(selection)
        todo = [i for i in instances if i.instance_id not in done][: limit or None]
        for instance in todo:
            agent = agent_factory(config)
            trajectory = _run_one(agent, instance, config)
            save_trajectory(trajectory, out_dir / "trajectories")
            row = summary_row(trajectory, config) | {"git_commit": git_commit()}
            with results_file.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(row) + "\n")
            rows.append(row)
            if on_result:
                on_result(row)
    return rows


def _run_one(agent: Agent, instance: BenchmarkInstance, config: ExperimentConfig) -> Trajectory:
    run_config = {"experiment": config.id, "llm": config.llm.model_dump(), "seed": config.seed}
    if instance.benchmark == "swebench-lite":
        from patchpilot.benchmarks import swebench

        with swebench.pulled_image(instance.image, prune=False):
            return agent.run(instance, run_config)
    return agent.run(instance, run_config)


def _done_ids(results_file: Path) -> set[str]:
    if not results_file.exists():
        return set()
    return {
        json.loads(line)["instance_id"]
        for line in results_file.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
