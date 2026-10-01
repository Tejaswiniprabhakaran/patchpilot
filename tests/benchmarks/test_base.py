from unittest.mock import MagicMock

from patchpilot.benchmarks import BenchmarkInstance, evaluate_patch, is_resolved
from patchpilot.sandbox import ExecResult, TestRunResult, TestStatus

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
        "gold_patch": "--- a/x\n+++ b/x\n",
    }
    fields.update(overrides)
    return BenchmarkInstance.model_validate(fields)


def test_resolved_needs_fail_to_pass_and_pass_to_pass() -> None:
    instance = make_instance(fail_to_pass=("t::a",), pass_to_pass=("t::b",))

    assert is_resolved(instance, TestRunResult({"t::a": P, "t::b": P})) == (True, True)
    assert is_resolved(instance, TestRunResult({"t::a": P, "t::b": F})) == (True, False)
    assert is_resolved(instance, TestRunResult({"t::a": F, "t::b": P})) == (False, True)
    # A target test that never ran is not a pass.
    assert is_resolved(instance, TestRunResult({"t::b": P})) == (False, True)


def test_without_enumerated_tests_every_test_must_pass() -> None:
    instance = make_instance()

    assert is_resolved(instance, TestRunResult({"a": P, "b": P})) == (True, True)
    assert is_resolved(instance, TestRunResult({"a": P, "b": F})) == (False, False)
    assert is_resolved(instance, TestRunResult({})) == (False, False)


def test_timeout_is_never_resolved() -> None:
    instance = make_instance()

    assert is_resolved(instance, TestRunResult({"a": P}, timed_out=True)) == (False, False)


def test_evaluate_patch_stops_when_patch_does_not_apply() -> None:
    box = MagicMock()
    box.apply_patch.return_value = ExecResult(exit_code=1, output="rejected", duration_s=0)

    result = evaluate_patch(make_instance(), "bad", sandbox=box)

    assert not result.applied
    assert not result.resolved
    assert result.apply_output == "rejected"
    box.reset.assert_called_once()
    box.run_tests.assert_not_called()
    box.stop.assert_not_called()  # caller owns the sandbox


def test_evaluate_patch_applies_test_patch_then_runs_tests() -> None:
    box = MagicMock()
    box.apply_patch.return_value = ExecResult(exit_code=0, output="", duration_s=0)
    box.run_tests.return_value = TestRunResult({"t::a": P})
    instance = make_instance(fail_to_pass=("t::a",), test_patch="TEST")

    result = evaluate_patch(instance, "FIX", sandbox=box)

    assert [c.args[0] for c in box.apply_patch.call_args_list] == ["FIX", "TEST"]
    assert result.resolved
