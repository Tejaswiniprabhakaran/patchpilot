import gzip
import json
from pathlib import Path

import pytest
from tests.fakes import FakeSandbox, make_instance
from typer.testing import CliRunner

from patchpilot import cli
from patchpilot.agent import Agent, AgentConfig, LLMSearchLocalizer
from patchpilot.config import BenchmarkSelection, ExperimentConfig
from patchpilot.evaluation.runner import run_experiment
from patchpilot.llm import ScriptedClient

LOCATE = '{"keywords": ["add"], "files": ["pkg/mod.py"]}'
GOOD = "pkg/mod.py\n<<<<<<< SEARCH\n    return a - b\n=======\n    return a + b\n>>>>>>> REPLACE\n"


def scripted_agent(_config: ExperimentConfig) -> Agent:
    llm = ScriptedClient([LOCATE, GOOD])
    box = FakeSandbox()
    return Agent(
        llm,
        LLMSearchLocalizer(llm),
        AgentConfig(max_attempts=2),
        sandbox_factory=lambda _i: box,  # type: ignore[arg-type,return-value]
    )


@pytest.fixture
def config(tmp_path: Path) -> ExperimentConfig:
    return ExperimentConfig(
        id="T0",
        benchmarks=[BenchmarkSelection(name="quixbugs")],
        results_dir=tmp_path,
    )


def instances() -> dict[str, list]:  # type: ignore[type-arg]
    return {"quixbugs": [make_instance(instance_id="a"), make_instance(instance_id="b")]}


def test_run_experiment_writes_rows_config_and_trajectories(config: ExperimentConfig) -> None:
    rows = run_experiment(config, agent_factory=scripted_agent, instances_override=instances())

    out = config.output_dir()
    lines = (out / "quixbugs.jsonl").read_text().splitlines()
    assert [json.loads(line)["instance_id"] for line in lines] == ["a", "b"]
    assert all(r["resolved"] for r in rows)
    assert rows[0]["experiment"] == "T0"
    assert rows[0]["llm_calls"] == 2
    assert (out / "config.yaml").exists()
    trajectories = sorted((out / "trajectories").glob("*.json.gz"))
    assert len(trajectories) == 2
    with gzip.open(trajectories[0], "rt") as handle:
        assert json.load(handle)["result"]["resolved"] is True


def test_run_experiment_resumes_and_respects_limit(config: ExperimentConfig) -> None:
    first = run_experiment(
        config, agent_factory=scripted_agent, instances_override=instances(), limit=1
    )
    second = run_experiment(config, agent_factory=scripted_agent, instances_override=instances())

    assert [r["instance_id"] for r in first] == ["a"]
    assert [r["instance_id"] for r in second] == ["b"]


def test_show_reads_gzipped_trajectory(
    config: ExperimentConfig, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    rows = run_experiment(config, agent_factory=scripted_agent, instances_override=instances())
    monkeypatch.setattr(cli, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(cli, "RUNS_DIR", tmp_path / "none")

    result = CliRunner().invoke(cli.app, ["show", rows[0]["run_id"]])

    assert result.exit_code == 0, result.output
    assert "RESOLVED" in result.output
    assert "localize_keywords" in result.output


def test_show_unknown_run_exits_with_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(cli, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(cli, "RUNS_DIR", tmp_path)

    result = CliRunner().invoke(cli.app, ["show", "nope"])

    assert result.exit_code == 1


def test_example_configs_are_valid() -> None:
    for path in Path("configs").glob("*.yaml"):
        ExperimentConfig.load(path)
