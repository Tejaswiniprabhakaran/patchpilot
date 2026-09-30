import subprocess
from pathlib import Path

import pytest

from patchpilot.benchmarks import quixbugs


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def fake_quixbugs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A tiny QuixBugs-shaped git repo; `buggy` uses CRLF line endings like upstream wrap.py."""
    root = tmp_path / "QuixBugs"
    for folder in ("python_programs", "correct_python_programs", "python_testcases"):
        (root / folder).mkdir(parents=True)
    (root / "python_programs" / "buggy.py").write_bytes(b"def buggy():\r\n    return 1\r\n")
    (root / "correct_python_programs" / "buggy.py").write_bytes(b"def buggy():\r\n    return 2\r\n")
    (root / "python_testcases" / "test_buggy.py").write_text("def test_x(): pass\n")
    # A program without a test file is not an instance.
    (root / "python_programs" / "orphan.py").write_text("x = 1\n")
    _git(root.parent, "init", "-q", str(root))
    _git(root, "config", "core.autocrlf", "false")
    _git(root, "add", "-A")
    _git(root, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "init")
    monkeypatch.setattr(quixbugs, "COMMIT", _git(root, "rev-parse", "HEAD"))
    return root


def test_program_names_requires_buggy_correct_and_test(fake_quixbugs: Path) -> None:
    assert quixbugs.program_names(fake_quixbugs) == ["buggy"]


def test_gold_patch_preserves_crlf_even_if_working_tree_was_rewritten(
    fake_quixbugs: Path,
) -> None:
    # Simulate a Windows autocrlf checkout that rewrote the working tree to LF.
    (fake_quixbugs / "python_programs" / "buggy.py").write_bytes(b"def buggy():\n    return 1\n")

    patch = quixbugs.gold_patch(fake_quixbugs, "buggy")

    assert "-    return 1\r\n" in patch
    assert "+    return 2\r\n" in patch
    assert patch.startswith("--- a/python_programs/buggy.py\n+++ b/python_programs/buggy.py\n")


def test_load_instance_describes_the_bug_and_test_command(fake_quixbugs: Path) -> None:
    instance = quixbugs.load_instance("buggy", fake_quixbugs)

    assert instance.benchmark == "quixbugs"
    assert instance.image == quixbugs.IMAGE
    assert "python_testcases/test_buggy.py" in instance.test_command
    assert "-rA" in instance.test_command
    assert f"--timeout={quixbugs.PER_TEST_TIMEOUT_S}" in instance.test_command
    assert "python_programs/buggy.py" in instance.problem_statement
    assert instance.fail_to_pass == ()


def test_unknown_program_raises(fake_quixbugs: Path) -> None:
    with pytest.raises(KeyError):
        quixbugs.load_instance("orphan", fake_quixbugs)


def test_missing_final_newline_is_marked() -> None:
    lines = list(quixbugs._with_final_newlines(["a\n", "b"]))

    assert lines == ["a\n", "b\n", "\\ No newline at end of file\n"]
