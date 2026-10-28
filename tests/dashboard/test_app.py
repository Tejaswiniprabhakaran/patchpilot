"""Dashboard tests with temporary results and a fake live-run function (no Docker, no model)."""

from __future__ import annotations

import gzip
import json
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from patchpilot.agent import Trajectory
from patchpilot.dashboard.app import RESERVED_PORTS, check_port, create_app

PATCH = "--- a/p.py\n+++ b/p.py\n@@ -1 +1 @@\n-x = 1\n+x = 2\n"


def write_results(root: Path) -> None:
    exp = root / "B0"
    (exp / "trajectories").mkdir(parents=True)
    row = {
        "experiment": "B0",
        "benchmark": "quixbugs",
        "instance_id": "gcd",
        "run_id": "gcd-1",
        "resolved": True,
        "attempts_used": 1,
        "wall_s": 12.0,
        "llm_calls": 2,
        "prompt_tokens": 100,
        "completion_tokens": 20,
    }
    other = row | {"instance_id": "kth", "run_id": "kth-1", "resolved": False}
    (exp / "quixbugs.jsonl").write_text(json.dumps(row) + "\n" + json.dumps(other) + "\n")
    trajectory = {
        "run_id": "gcd-1",
        "benchmark": "quixbugs",
        "instance_id": "gcd",
        "config": {},
        "started_at": "now",
        "steps": [
            {
                "index": 0,
                "kind": "tool",
                "name": "run_tests",
                "input": {},
                "output": "1 failed",
                "ok": True,
                "duration_s": 1.0,
                "timestamp": "t",
                "meta": {},
            },
            {
                "index": 1,
                "kind": "tool",
                "name": "submit",
                "input": {"attempt": 1},
                "output": PATCH,
                "ok": True,
                "duration_s": 0.1,
                "timestamp": "t",
                "meta": {},
            },
        ],
        "result": {
            "resolved": True,
            "attempts_used": 1,
            "final_patch": PATCH,
            "localized_files": ["p.py"],
            "wall_s": 12.0,
            "llm_calls": 2,
            "prompt_tokens": 100,
            "completion_tokens": 20,
        },
    }
    with gzip.open(exp / "trajectories" / "gcd-1.json.gz", "wt", encoding="utf-8") as handle:
        json.dump(trajectory, handle)


def fake_run(instance_id: str, on_step: Any, run_id: str) -> Trajectory:
    trajectory = Trajectory(run_id, "quixbugs", instance_id, {})
    trajectory.set_listener(on_step)
    trajectory.add("tool", "run_tests", {}, "1 failed")
    trajectory.result = {"resolved": True, "attempts_used": 1, "final_patch": PATCH, "wall_s": 1.0}
    return trajectory


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    write_results(tmp_path / "results")
    app = create_app(
        results_dir=tmp_path / "results",
        runs_dir=tmp_path / "runs",
        figures_dir=tmp_path / "figures",
        health=lambda: {"docker": True, "ollama": True},
        run=fake_run,
        instance_ids=lambda: ["gcd", "kth"],
    )
    return TestClient(app)


def test_runs_page_lists_and_filters_runs(client: TestClient) -> None:
    page = client.get("/")
    resolved_only = client.get("/?status=resolved")

    assert page.status_code == 200
    assert "gcd" in page.text and "kth" in page.text
    assert "Showing 2 of 2 runs" in page.text
    assert "gcd" in resolved_only.text and "kth" not in resolved_only.text


def test_run_page_shows_steps_and_highlighted_diff(client: TestClient) -> None:
    page = client.get("/runs/B0/gcd-1")

    assert page.status_code == 200
    assert "run_tests" in page.text
    assert 'class="diff"' in page.text  # Pygments-highlighted patch
    assert "x = 2" in page.text


def test_unknown_or_path_traversal_runs_are_404(client: TestClient) -> None:
    assert client.get("/runs/B0/nope").status_code == 404
    assert client.get("/runs/..%2F..%2Fsecrets/x").status_code == 404


def test_metrics_page_says_todo_when_nothing_was_generated(client: TestClient) -> None:
    page = client.get("/metrics")

    assert page.status_code == 200
    assert "TODO" in page.text


def test_try_runs_one_job_and_streams_steps(client: TestClient) -> None:
    started = client.post("/api/try", json={"instance_id": "gcd"})
    assert started.status_code == 200
    run_id = started.json()["run_id"]

    for _ in range(50):
        status = client.get(f"/api/try/{run_id}").json()
        if status["state"] != "running":
            break
        time.sleep(0.05)

    assert status["state"] == "done"
    assert [s["name"] for s in status["steps"]] == ["run_tests"]
    assert status["result"]["resolved"] is True
    assert 'class="diff"' in status["patch_html"]
    # The finished run is saved and appears in the run list as a 'fix' run.
    assert "gcd" in client.get("/?experiment=fix").text


def test_try_rejects_unknown_programs_and_missing_services(tmp_path: Path) -> None:
    app = create_app(
        results_dir=tmp_path,
        runs_dir=tmp_path / "runs",
        figures_dir=tmp_path,
        health=lambda: {"docker": False, "ollama": True},
        run=fake_run,
        instance_ids=lambda: ["gcd"],
    )
    client = TestClient(app)

    assert client.post("/api/try", json={"instance_id": "evil"}).status_code == 400
    assert client.post("/api/try", json={"instance_id": "gcd"}).status_code == 503


def test_reserved_ports_are_refused() -> None:
    assert {8081, 3001, 5433, 7100, 5000} <= RESERVED_PORTS
    with pytest.raises(ValueError):
        check_port(8081)
    check_port(8765)
