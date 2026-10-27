"""Shared test doubles: an in-memory sandbox whose 'tests' pass once the file is fixed."""

from __future__ import annotations

import json
from collections.abc import Callable

from patchpilot.benchmarks import BenchmarkInstance
from patchpilot.sandbox import ExecResult, TestRunResult, TestStatus

BUGGY = "def add(a, b):\n    return a - b\n"
FIXED = "def add(a, b):\n    return a + b\n"
DIFF_PREFIX = "FAKEDIFF:"


def make_instance(**overrides: object) -> BenchmarkInstance:
    fields: dict[str, object] = {
        "benchmark": "demo",
        "instance_id": "demo-1",
        "repo": "o/r",
        "base_commit": "abc",
        "image": "img",
        "problem_statement": "add() subtracts instead of adding.",
        "test_command": "pytest -rA",
        "gold_patch": "",
        "protected_paths": ("tests/",),
    }
    fields.update(overrides)
    return BenchmarkInstance.model_validate(fields)


def adds_correctly(files: dict[str, str]) -> TestRunResult:
    ok = "a + b" in files.get("pkg/mod.py", "")
    status = TestStatus.PASSED if ok else TestStatus.FAILED
    return TestRunResult({"tests/test_mod.py::test_add": status}, output=f"test_add {status}")


class FakeSandbox:
    def __init__(
        self,
        files: dict[str, str] | None = None,
        judge: Callable[[dict[str, str]], TestRunResult] = adds_correctly,
    ) -> None:
        self.original = dict(files if files is not None else {"pkg/mod.py": BUGGY})
        self.files = dict(self.original)
        self.judge = judge
        self.started = False
        self.stopped = False
        self.test_runs = 0

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True

    def exec(self, command: str, timeout_s: int | None = None, truncate: bool = True) -> ExecResult:
        if command.startswith("git ls-files"):
            return ExecResult(0, "\n".join(sorted(self.files)), 0.0)
        if "rg --no-heading" in command:
            hits = [f"./{p}:1:{c.splitlines()[0]}" for p, c in self.files.items()]
            return ExecResult(0, "\n".join(hits), 0.0)
        return ExecResult(0, "", 0.0)

    def read_file(self, path: str) -> str:
        if path not in self.files:
            raise FileNotFoundError(path)
        return self.files[path]

    def write_file(self, path: str, content: str) -> None:
        self.files[path] = content

    def run_tests(
        self, command: str, timeout_s: int | None = None, parser: object = None
    ) -> TestRunResult:
        self.test_runs += 1
        return self.judge(self.files)

    def apply_patch(self, diff: str) -> ExecResult:
        if not diff.startswith(DIFF_PREFIX):
            return ExecResult(1, "patch does not apply", 0.0)
        self.files.update(json.loads(diff.removeprefix(DIFF_PREFIX)))
        return ExecResult(0, "applied", 0.0)

    def diff(self, exclude: tuple[str, ...] = ()) -> str:
        changed = {p: c for p, c in self.files.items() if self.original.get(p) != c}
        return DIFF_PREFIX + json.dumps(changed) if changed else ""

    def reset(self) -> None:
        self.files = dict(self.original)
