"""Unit tests for the agent tools, using an in-memory fake sandbox."""

from __future__ import annotations

import pytest

from patchpilot.benchmarks import BenchmarkInstance
from patchpilot.sandbox import ExecResult, TestRunResult, TestStatus
from patchpilot.tools import Toolbox, apply_search_replace, summarise_tests
from patchpilot.tools.toolbox import _safe_path

P, F = TestStatus.PASSED, TestStatus.FAILED


def make_instance(**overrides: object) -> BenchmarkInstance:
    fields: dict[str, object] = {
        "benchmark": "demo",
        "instance_id": "demo-1",
        "repo": "o/r",
        "base_commit": "abc",
        "image": "img",
        "problem_statement": "broken",
        "test_command": "pytest -rA",
        "gold_patch": "",
        "protected_paths": ("tests/", "conftest.py"),
    }
    fields.update(overrides)
    return BenchmarkInstance.model_validate(fields)


class FakeSandbox:
    """Files in a dict; exec answers the few commands the toolbox issues."""

    def __init__(self, files: dict[str, str], compiles: bool = True) -> None:
        self.files = dict(files)
        self.compiles = compiles
        self.commands: list[str] = []
        self.patches: list[str] = []
        self.tests = TestRunResult({"tests/t.py::test_a": F}, output="E assert 1 == 2")

    def exec(self, command: str, timeout_s: int | None = None, truncate: bool = True) -> ExecResult:
        self.commands.append(command)
        if command.startswith("git ls-files"):
            return ExecResult(0, "\n".join(sorted(self.files)), 0.1)
        if command.startswith("python -m py_compile"):
            return ExecResult(0 if self.compiles else 1, "" if self.compiles else "SyntaxError", 0)
        if "rg --no-heading" in command:
            return ExecResult(0, "./pkg/mod.py:2:    return a - b\n", 0.1)
        return ExecResult(0, "", 0)

    def read_file(self, path: str) -> str:
        if path not in self.files:
            raise FileNotFoundError(path)
        return self.files[path]

    def write_file(self, path: str, content: str) -> None:
        self.files[path] = content

    def run_tests(self, command: str, timeout_s: int | None = None, parser: object = None):  # type: ignore[no-untyped-def]
        return self.tests

    def apply_patch(self, diff: str) -> ExecResult:
        self.patches.append(diff)
        return ExecResult(0, "applied", 0)

    def diff(self, exclude: tuple[str, ...] = ()) -> str:
        self.diff_exclude = exclude
        return "--- a/pkg/mod.py\n+++ b/pkg/mod.py\n"

    def reset(self) -> None:
        self.commands.append("reset")


SOURCE = "def add(a, b):\n    return a - b\n\n\ndef sub(a, b):\n    return a - b\n"


def toolbox(files: dict[str, str] | None = None, **kwargs: object) -> tuple[Toolbox, FakeSandbox]:
    box = FakeSandbox(files if files is not None else {"pkg/mod.py": SOURCE})
    return Toolbox(box, make_instance(**kwargs)), box  # type: ignore[arg-type]


def test_read_file_numbers_lines_and_clamps_range() -> None:
    tools, _ = toolbox()

    result = tools.read_file("pkg/mod.py", 2, 3)

    assert result.ok
    assert result.output.splitlines()[0] == "pkg/mod.py (lines 2-3 of 6)"
    assert result.output.splitlines()[1] == "     2      return a - b"


def test_read_file_errors_are_reported_not_raised() -> None:
    tools, _ = toolbox()

    assert not tools.read_file("missing.py").ok
    assert not tools.read_file("pkg/mod.py", 50).ok
    assert not tools.read_file("../etc/passwd").ok
    assert not tools.read_file("/etc/passwd").ok


def test_edit_requires_a_unique_match() -> None:
    tools, box = toolbox()

    ambiguous = tools.edit_file("pkg/mod.py", "    return a - b\n", "    return a + b\n")
    unique = tools.edit_file(
        "pkg/mod.py", "def add(a, b):\n    return a - b\n", "def add(a, b):\n    return a + b\n"
    )

    assert not ambiguous.ok
    assert "matches 2 places" in ambiguous.output
    assert unique.ok
    assert box.files["pkg/mod.py"].startswith("def add(a, b):\n    return a + b\n")


def test_edit_that_breaks_compilation_is_undone() -> None:
    tools, box = toolbox()
    box.compiles = False

    result = tools.edit_file("pkg/mod.py", "def add(a, b):", "def add(a, b")

    assert not result.ok
    assert "no longer compiles" in result.output
    assert box.files["pkg/mod.py"] == SOURCE


def test_test_files_are_protected() -> None:
    tools, _ = toolbox({"tests/test_mod.py": "x", "conftest.py": "y"})

    assert not tools.edit_file("tests/test_mod.py", "x", "z").ok
    assert not tools.edit_file("conftest.py", "y", "z").ok


def test_prepare_applies_the_failing_test_patch() -> None:
    tools, box = toolbox(agent_test_patch="TESTS")

    assert tools.prepare().ok
    assert box.commands[0] == "reset"
    assert box.patches == ["TESTS"]


def test_run_tests_reapplies_test_patch_and_summarises() -> None:
    tools, box = toolbox(agent_test_patch="TESTS", fail_to_pass=("tests/t.py::test_a",))

    result = tools.run_tests()

    assert box.patches == ["TESTS"]
    assert "Target tests passing: 0/1" in result.output
    assert "still failing: tests/t.py::test_a" in result.output
    assert tools.last_tests is box.tests


def test_submit_excludes_protected_paths() -> None:
    tools, box = toolbox()

    result = tools.submit()

    assert result.ok
    assert box.diff_exclude == ("tests/", "conftest.py")


def test_search_strips_leading_dot_slash() -> None:
    tools, _ = toolbox()

    assert tools.search_code("a - b").output == "pkg/mod.py:2:    return a - b"
    assert not tools.search_code("  ").ok


def test_list_files_lists_tracked_files() -> None:
    tools, _ = toolbox()

    assert tools.list_files().output == "pkg/mod.py"


def test_search_replace_ignores_indentation_differences() -> None:
    original = "class A:\n    def f(self):\n        return 1\n"

    updated, problem = apply_search_replace(
        original, "def f(self):\n    return 1\n", "def f(self):\n    return 2\n"
    )

    assert problem == ""
    assert updated == "class A:\n    def f(self):\n        return 2\n"


def test_search_replace_reports_missing_block() -> None:
    updated, problem = apply_search_replace("a\n", "zzz\n", "y\n")

    assert updated is None
    assert "not found" in problem


@pytest.mark.parametrize(
    ("raw", "safe"),
    [(".", "."), ("", "."), ("./a/b.py", "a/b.py"), ("a/../b.py", "b.py"), ("../x", None)],
)
def test_safe_path(raw: str, safe: str | None) -> None:
    assert _safe_path(raw) == safe


def test_summary_without_enumerated_tests_lists_failures() -> None:
    text = summarise_tests(make_instance(), TestRunResult({"a": P, "b": F}, output="boom"))

    assert "Passed: 1  Failed: 1" in text
    assert "failing: b" in text
    assert text.endswith("boom")


def test_summary_reports_broken_previously_passing_tests() -> None:
    instance = make_instance(fail_to_pass=("t::new",), pass_to_pass=("t::old",))

    text = summarise_tests(instance, TestRunResult({"t::new": P, "t::old": F}))

    assert "Target tests passing: 1/1" in text
    assert "broken: t::old" in text
    assert "Tests are not passing yet." in text


def test_missing_block_feedback_shows_the_closest_real_lines() -> None:
    original = "def gcd(a, b):\n    if b == 0:\n        return a\n    return gcd(a % b, b)\n"

    updated, problem = apply_search_replace(original, "return gcd(a%b , b)\n", "x\n")

    assert updated is None
    assert "    return gcd(a % b, b)" in problem
    assert "without line numbers" in problem
