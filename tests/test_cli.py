import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from patchpilot import __version__
from patchpilot.cli import app

runner = CliRunner()


def test_version_command_prints_package_version() -> None:
    result = runner.invoke(app, ["version"])

    assert result.exit_code == 0
    assert result.stdout.strip() == f"patchpilot {__version__}"


def test_no_args_shows_help() -> None:
    result = runner.invoke(app, [])

    assert "Usage" in result.output


def test_show_prints_code_literally(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    trajectory = {
        "benchmark": "quixbugs",
        "instance_id": "bucketsort",
        "run_id": "bucketsort-1",
        "steps": [
            {
                "index": 0,
                "kind": "tool",
                "name": "edit_file",
                "ok": True,
                "duration_s": 0.5,
                "input": {"path": "p.py"},
                "output": "sorted_arr.extend([i] * count)",
            }
        ],
        "result": {"resolved": True, "error": "KeyError: [missing]", "localized_files": ["p.py"]},
    }
    (tmp_path / "runs").mkdir()
    (tmp_path / "runs" / "bucketsort-1.json").write_text(json.dumps(trajectory))
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["show", "bucketsort-1"], env={"COLUMNS": "200"})

    assert result.exit_code == 0
    assert "sorted_arr.extend([i] * count)" in result.output
    assert "KeyError: [missing]" in result.output
