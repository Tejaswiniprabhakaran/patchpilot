import gzip
import json
from pathlib import Path

from patchpilot.evaluation.infra import infra_reason, split_rows


def write_trajectory(directory: Path, run_id: str, llm_seconds: list[float]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    steps = [{"kind": "llm", "duration_s": s} for s in llm_seconds]
    steps.append({"kind": "tool", "duration_s": 99_999.0})  # slow tools are not stalls
    with gzip.open(directory / f"{run_id}.json.gz", "wt", encoding="utf-8") as handle:
        json.dump({"steps": steps}, handle)


def row(instance_id: str, error: str | None = None, resolved: bool = False) -> dict:  # type: ignore[type-arg]
    return {
        "instance_id": instance_id,
        "run_id": f"{instance_id}-1",
        "error": error,
        "resolved": resolved,
    }


def test_stalled_model_call_is_an_infra_failure_even_if_resolved(tmp_path: Path) -> None:
    write_trajectory(tmp_path, "a-1", [120.0, 3799.0])

    assert "3799 s" in (infra_reason(row("a", resolved=True), tmp_path) or "")


def test_server_errors_are_infra_failures(tmp_path: Path) -> None:
    assert infra_reason(row("b", error="APITimeoutError: Request timed out."), tmp_path)
    assert infra_reason(row("c", error="ValueError: bad edit"), tmp_path) is None


def test_normal_runs_are_kept(tmp_path: Path) -> None:
    write_trajectory(tmp_path, "d-1", [300.0, 600.0])

    assert infra_reason(row("d"), tmp_path) is None


def write_token_trajectory(directory: Path, run_id: str, calls: list[tuple[int, int]]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    steps = [
        {"kind": "llm", "duration_s": 60.0, "meta": {"prompt_tokens": p, "completion_tokens": c}}
        for p, c in calls
    ]
    with gzip.open(directory / f"{run_id}.json.gz", "wt", encoding="utf-8") as handle:
        json.dump({"steps": steps}, handle)


def test_a_call_that_filled_the_context_window_is_an_infra_failure(tmp_path: Path) -> None:
    write_token_trajectory(tmp_path, "a-1", [(1500, 300), (2175, 1917)])  # 4,092 of 4,096
    write_token_trajectory(tmp_path, "d-1", [(3000, 500)])

    reason = infra_reason(row("a", resolved=True), tmp_path, context_window=4096)

    assert reason and "4092 tokens" in reason
    assert infra_reason(row("d"), tmp_path, context_window=4096) is None
    assert infra_reason(row("a"), tmp_path) is None  # only checked when the window is given


def test_each_instance_is_requeued_at_most_once(tmp_path: Path) -> None:
    write_trajectory(tmp_path, "a-1", [4000.0])
    write_trajectory(tmp_path, "d-1", [10.0])

    keep, requeue = split_rows([row("a"), row("d")], tmp_path, already_requeued=set())
    keep_again, requeue_again = split_rows([row("a")], tmp_path, already_requeued={"a"})

    assert [r["instance_id"] for r in requeue] == ["a"]
    assert [r["instance_id"] for r in keep] == ["d"]
    assert requeue_again == [] and keep_again[0]["instance_id"] == "a"
