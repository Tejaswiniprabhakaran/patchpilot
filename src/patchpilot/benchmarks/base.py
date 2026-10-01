"""Benchmark-independent description of one bug and how to check a fix for it."""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field

from patchpilot.sandbox import (
    DockerSandbox,
    SandboxLimits,
    TestRunResult,
    TestStatus,
    parse_pytest_summary,
)
from patchpilot.sandbox.docker_sandbox import TestParser


class BenchmarkInstance(BaseModel):
    """One bug: where its code lives, what is wrong, and which tests decide if it is fixed."""

    model_config = ConfigDict(frozen=True)

    benchmark: str
    instance_id: str
    repo: str
    base_commit: str
    image: str
    workdir: str = "/testbed"
    shell_prefix: str = ""
    problem_statement: str
    # Command that runs the target tests and prints a parseable per-test summary.
    test_command: str
    # Tests that fail before the fix and must pass after it. Empty means "not enumerated":
    # the instance is then resolved when every test run by `test_command` passes.
    fail_to_pass: tuple[str, ...] = ()
    # Tests that pass before the fix and must still pass after it.
    pass_to_pass: tuple[str, ...] = ()
    gold_patch: str
    # Applied before running tests (SWE-bench adds the tests that expose the bug this way).
    test_patch: str = ""
    # Files written into the sandbox right before the tests run (e.g. SWE-bench's eval script).
    setup_files: dict[str, str] = Field(default_factory=dict)
    # How to read the test output: "pytest" (our -rA parser) or "swebench" (official parsers).
    log_parser: str = "pytest"
    test_timeout_s: int = 300
    memory: str = "2g"

    def limits(self) -> SandboxLimits:
        return SandboxLimits(memory=self.memory, timeout_s=self.test_timeout_s)

    def sandbox(self) -> DockerSandbox:
        return DockerSandbox(
            self.image,
            workdir=self.workdir,
            limits=self.limits(),
            shell_prefix=self.shell_prefix,
        )


@dataclass(frozen=True)
class PatchEvaluation:
    """Result of applying one candidate patch to one instance and running its tests."""

    instance_id: str
    applied: bool
    resolved: bool
    fail_to_pass_ok: bool
    pass_to_pass_ok: bool
    tests: TestRunResult
    apply_output: str = ""


def is_resolved(instance: BenchmarkInstance, tests: TestRunResult) -> tuple[bool, bool]:
    """Return ``(fail_to_pass_ok, pass_to_pass_ok)`` for a test run.

    An instance counts as resolved only when both are true: every target test passes AND no
    previously passing test broke.
    """
    if tests.timed_out:
        return False, False
    if not instance.fail_to_pass:
        ok = tests.all_passed
        return ok, ok

    def all_pass(names: tuple[str, ...]) -> bool:
        return all(tests.statuses.get(name) is TestStatus.PASSED for name in names)

    return all_pass(instance.fail_to_pass), all_pass(instance.pass_to_pass)


def run_instance_tests(instance: BenchmarkInstance, sandbox: DockerSandbox) -> TestRunResult:
    """Run the instance's target tests in an already-started sandbox."""
    for path, content in instance.setup_files.items():
        sandbox.write_file(path, content)
    return sandbox.run_tests(
        instance.test_command, timeout_s=instance.test_timeout_s, parser=log_parser_for(instance)
    )


def log_parser_for(instance: BenchmarkInstance) -> TestParser:
    if instance.log_parser == "pytest":
        return parse_pytest_summary
    if instance.log_parser == "swebench":
        from patchpilot.benchmarks import swebench

        return swebench.parser_for(instance.instance_id)
    raise ValueError(f"unknown log parser: {instance.log_parser}")


def evaluate_patch(
    instance: BenchmarkInstance, patch: str, sandbox: DockerSandbox | None = None
) -> PatchEvaluation:
    """Apply ``patch`` to a fresh checkout of the instance and run its target tests."""
    own_sandbox = sandbox is None
    box = sandbox or instance.sandbox()
    if own_sandbox:
        box.start()
    try:
        box.reset()
        applied = box.apply_patch(patch)
        if not applied.ok:
            return PatchEvaluation(
                instance_id=instance.instance_id,
                applied=False,
                resolved=False,
                fail_to_pass_ok=False,
                pass_to_pass_ok=False,
                tests=TestRunResult(),
                apply_output=applied.output,
            )
        if instance.test_patch:
            test_patch = box.apply_patch(instance.test_patch)
            if not test_patch.ok:
                return PatchEvaluation(
                    instance_id=instance.instance_id,
                    applied=True,
                    resolved=False,
                    fail_to_pass_ok=False,
                    pass_to_pass_ok=False,
                    tests=TestRunResult(),
                    apply_output=f"test patch did not apply:\n{test_patch.output}",
                )
        tests = run_instance_tests(instance, box)
        f2p, p2p = is_resolved(instance, tests)
        return PatchEvaluation(
            instance_id=instance.instance_id,
            applied=True,
            resolved=f2p and p2p,
            fail_to_pass_ok=f2p,
            pass_to_pass_ok=p2p,
            tests=tests,
            apply_output=applied.output,
        )
    finally:
        if own_sandbox:
            box.stop()
