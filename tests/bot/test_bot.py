from __future__ import annotations

import contextlib
import io
import json
import subprocess
import tarfile
from pathlib import Path
from typing import Any

import pytest

from patchpilot.agent import Trajectory
from patchpilot.benchmarks import BenchmarkInstance
from patchpilot.bot import __main__ as bot
from patchpilot.bot.comment import MARKER, format_comment
from patchpilot.bot.local_repo import build_context, make_instance
from patchpilot.sandbox import TestRunResult, TestStatus

PATCH = (
    "--- a/calc.py\n+++ b/calc.py\n@@ -1,2 +1,2 @@\n"
    " def add(a, b):\n-    return a - b\n+    return a + b\n"
)


def git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "calc.py").write_text("def add(a, b):\n    return a - b\n")
    (repo / "tests").mkdir()
    (repo / "tests" / "test_calc.py").write_text(
        "from calc import add\n\ndef test_add():\n    assert add(1, 2) == 3\n"
    )
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@t",
            "commit",
            "-q",
            "-m",
            "x",
        ],
        check=True,
    )
    (repo / "untracked_secret.txt").write_text("not for the image")
    return repo


def test_build_context_contains_tracked_files_and_dockerfile_only(tmp_path: Path) -> None:
    repo = git_repo(tmp_path)

    with tarfile.open(fileobj=io.BytesIO(build_context(repo))) as tar:
        names = set(tar.getnames())
        dockerfile = tar.extractfile("Dockerfile.patchpilot")
        assert dockerfile is not None
        text = dockerfile.read().decode()

    assert names == {"calc.py", "tests/test_calc.py", "Dockerfile.patchpilot"}
    assert "FROM python:3.11-slim" in text
    assert "pytest-timeout" in text


def test_instance_protects_tests_and_has_no_gold_patch() -> None:
    instance = make_instance("o/r", "abcdef123456", "img", "pytest -rA", "fails")

    assert instance.protected_paths == ("tests/",)
    assert instance.gold_patch == ""
    assert instance.instance_id == "o__r-abcdef12"


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        ({"resolved": True, "final_patch": PATCH, "attempts_used": 1}, "makes them pass"),
        ({"resolved": False, "final_patch": PATCH, "attempts_used": 2}, "did **not** make every"),
        ({"resolved": False, "final_patch": "", "attempts_used": 2}, "could not produce a fix"),
    ],
)
def test_comment_wording_matches_the_outcome(result: dict[str, Any], expected: str) -> None:
    body = format_comment(result, "1 failed", "1 passed", "gemma4:e4b")

    assert body.startswith(MARKER)
    assert expected in body
    assert "never pushes commits or merges" in body
    assert ("```diff" in body) == bool(result["final_patch"])


def test_pull_request_context_and_problem_statement(tmp_path: Path) -> None:
    event = tmp_path / "event.json"
    event.write_text(
        json.dumps({"pull_request": {"number": 7, "title": "Add totals", "body": "Adds add()."}})
    )

    context = bot.pull_request_context(str(event))
    problem = bot.problem_statement(context, "pytest -rA")

    assert context == {"number": 7, "title": "Add totals", "body": "Adds add()."}
    assert "Add totals" in problem and "`pytest -rA` fails" in problem
    assert bot.pull_request_context(None) == {}


class FakeAgent:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    def run(self, instance: Any, run_config: Any = None) -> Trajectory:
        trajectory = Trajectory("r-1", "pull-request", instance.instance_id, {})
        trajectory.add("tool", "evaluate", {}, "PASSED tests/test_calc.py::test_add")
        trajectory.result = {
            "resolved": True,
            "final_patch": PATCH,
            "attempts_used": 1,
            "localized_files": ["calc.py"],
            "wall_s": 3.0,
        }
        return trajectory


@pytest.fixture
def fake_world(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    repo = git_repo(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_EVENT_PATH", raising=False)
    monkeypatch.setattr(bot, "build_image", lambda repo, tag: tag)
    monkeypatch.setattr(
        BenchmarkInstance,
        "sandbox",
        lambda self: contextlib.nullcontext(object()),
        raising=False,
    )
    monkeypatch.setattr(bot, "Agent", FakeAgent)
    monkeypatch.setattr(bot, "OpenAICompatibleClient", lambda config: object())
    return repo


def test_bot_stays_quiet_when_tests_pass(
    fake_world: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    passing = TestRunResult({"tests/test_calc.py::test_add": TestStatus.PASSED})
    monkeypatch.setattr(bot, "run_instance_tests", lambda instance, box: passing)

    assert bot.main(["--repo-dir", str(fake_world), "--dry-run"]) == 0
    assert "nothing to do" in capsys.readouterr().out


def test_bot_proposes_a_fix_when_tests_fail(
    fake_world: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    failing = TestRunResult(
        {"tests/test_calc.py::test_add": TestStatus.FAILED}, output="E assert -1 == 3"
    )
    monkeypatch.setattr(bot, "run_instance_tests", lambda instance, box: failing)

    assert bot.main(["--repo-dir", str(fake_world), "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "makes them pass" in out
    assert "+    return a + b" in out
    assert any(Path("runs").glob("*.json"))  # trajectory kept for the workflow artifact
