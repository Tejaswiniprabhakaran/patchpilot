import pytest

from patchpilot.analysis.failures import classify, cohen_kappa, passing_tests
from patchpilot.analysis.judge import classify_with_judge, problem_text
from patchpilot.llm import ScriptedClient

GOLD = (
    "--- a/pkg/mod.py\n+++ b/pkg/mod.py\n@@ -10,1 +10,1 @@\n-    return a - b\n+    return a + b\n"
)
NEAR = "--- a/pkg/mod.py\n+++ b/pkg/mod.py\n@@ -11,1 +11,1 @@\n-    x = 1\n+    x = 2\n"
FAR = "--- a/pkg/mod.py\n+++ b/pkg/mod.py\n@@ -80,1 +80,1 @@\n-    y = 1\n+    y = 2\n"
OTHER = "--- a/pkg/other.py\n+++ b/pkg/other.py\n@@ -3,1 +3,1 @@\n-z\n+w\n"


def step(
    name: str,
    output: str = "",
    ok: bool = True,
    kind: str = "tool",
    duration: float = 1.0,
    **inp: object,
) -> dict:  # type: ignore[type-arg]
    return {
        "kind": kind,
        "name": name,
        "output": output,
        "ok": ok,
        "duration_s": duration,
        "input": inp,
    }


def trajectory(steps: list[dict], **result: object) -> dict:  # type: ignore[type-arg]
    return {
        "instance_id": "demo-1",
        "run_id": "demo-1-x",
        "config": {"agent": {"max_attempts": 3}},
        "steps": steps,
        "result": {"resolved": False, **result},
    }


TESTS_BEFORE = step("run_tests", "Target tests passing: 0/2\n...")
EDIT_OK = step("edit_file", "edited pkg/mod.py")


def test_crash_and_stall_are_environment_errors() -> None:
    crashed = trajectory([], error="DockerException: daemon gone")
    stalled = trajectory([step("repair", kind="llm", duration=4000.0)])

    assert classify(crashed, GOLD, ["pkg/mod.py"]).category == "environment"
    assert classify(stalled, GOLD, ["pkg/mod.py"]).category == "environment"


def test_no_applied_edit_is_patch_invalid() -> None:
    run = trajectory(
        [
            TESTS_BEFORE,
            step("no_edits", "No edit blocks", ok=False),
            step("edit_file", "SEARCH block was not found", ok=False),
        ],
        final_patch="",
    )

    result = classify(run, GOLD, ["pkg/mod.py"])

    assert result.category == "patch_invalid"
    assert len(result.evidence["examples"]) == 2


def test_editing_another_file_is_wrong_file() -> None:
    run = trajectory([TESTS_BEFORE, EDIT_OK], final_patch=OTHER, localized_files=["pkg/other.py"])

    assert classify(run, GOLD, ["pkg/mod.py"]).category == "wrong_file"


def test_target_pass_but_regressions_is_breaks_other_tests() -> None:
    run = trajectory(
        [TESTS_BEFORE, EDIT_OK], final_patch=NEAR, fail_to_pass_ok=True, pass_to_pass_ok=False
    )

    assert classify(run, GOLD, ["pkg/mod.py"]).category == "breaks_other_tests"


def test_far_away_edit_in_right_file_is_wrong_function() -> None:
    run = trajectory([TESTS_BEFORE, EDIT_OK], final_patch=FAR, fail_to_pass_ok=False)

    assert classify(run, GOLD, ["pkg/mod.py"]).category == "wrong_function"


def test_progress_in_right_region_is_incomplete_fix() -> None:
    run = trajectory(
        [TESTS_BEFORE, EDIT_OK, step("run_tests", "Target tests passing: 1/2")],
        final_patch=NEAR,
        fail_to_pass_ok=False,
        attempts_used=3,
    )

    result = classify(run, GOLD, ["pkg/mod.py"])

    assert result.category == "incomplete_fix"
    assert result.evidence["best_passing_after"] == 1


def test_no_progress_after_all_attempts_is_out_of_attempts() -> None:
    run = trajectory(
        [TESTS_BEFORE, EDIT_OK, step("run_tests", "Target tests passing: 0/2")],
        final_patch=NEAR,
        fail_to_pass_ok=False,
        attempts_used=3,
    )

    assert classify(run, GOLD, ["pkg/mod.py"]).category == "out_of_attempts"


def test_resolved_runs_are_rejected() -> None:
    with pytest.raises(ValueError):
        classify({"instance_id": "x", "run_id": "y", "result": {"resolved": True}}, GOLD, [])


def test_passing_tests_parses_both_summary_formats() -> None:
    assert passing_tests("Target tests passing: 3/5\n") == 3
    assert passing_tests("Passed: 7  Failed: 2\n") == 7
    assert passing_tests("no summary") is None


def test_cohen_kappa() -> None:
    assert cohen_kappa(["a", "b", "a", "b"], ["a", "b", "a", "b"]) == 1.0
    assert cohen_kappa(["a", "a", "b", "b"], ["a", "b", "a", "b"]) == pytest.approx(0.0)
    assert cohen_kappa(["a", "a"], ["a", "a"]) == 1.0
    with pytest.raises(ValueError):
        cohen_kappa(["a"], [])


def test_judge_reviews_only_uncertain_categories_and_validates_answers() -> None:
    uncertain = trajectory(
        [
            step(
                "repair", kind="llm", prompt="## Bug report\nadd() subtracts\n## Failing tests\n..."
            ),
            TESTS_BEFORE,
            EDIT_OK,
            step("run_tests", "Target tests passing: 0/2"),
        ],
        final_patch=NEAR,
        fail_to_pass_ok=False,
        attempts_used=3,
    )
    certain = trajectory([TESTS_BEFORE, EDIT_OK], final_patch=OTHER)

    llm = ScriptedClient(['{"category": "overfitting", "reason": "hard-codes the test value"}'])
    judged = classify_with_judge(uncertain, GOLD, ["pkg/mod.py"], llm)
    untouched = classify_with_judge(certain, GOLD, ["pkg/mod.py"], ScriptedClient([]))
    invalid = classify_with_judge(uncertain, GOLD, ["pkg/mod.py"], ScriptedClient(["no idea"]))

    assert (judged.category, judged.source) == ("overfitting", "judge")
    assert judged.evidence["rule_category"] == "out_of_attempts"
    assert "add() subtracts" in llm.prompts[0][0].content
    assert untouched.category == "wrong_file" and untouched.source == "rules"
    assert invalid.category == "out_of_attempts" and invalid.source == "rules"
    assert problem_text(uncertain) == "add() subtracts"


def test_code_regions_ignore_docstring_and_blank_line_changes() -> None:
    from patchpilot.analysis.failures import code_regions

    # A QuixBugs-style gold patch: one real fix plus deleting the trailing docstring.
    gold = (
        "--- a/p.py\n+++ b/p.py\n@@ -3,8 +3,3 @@\n     for x in xs:\n"
        "-        if x < j:\n+        if x <= j:\n             pass\n"
        '-\n-"""\n-Knapsack\n-text\n-"""\n'
    )

    assert code_regions(gold) == {"p.py": {4}}


def test_edit_next_to_a_deleted_docstring_is_not_the_right_place() -> None:
    gold = (
        "--- a/pkg/mod.py\n+++ b/pkg/mod.py\n@@ -10,1 +10,1 @@\n"
        "-    return a - b\n+    return a + b\n"
        '@@ -40,4 +40,0 @@\n-"""\n-docs\n-more docs\n-"""\n'
    )
    agent = "--- a/pkg/mod.py\n+++ b/pkg/mod.py\n@@ -41,1 +41,1 @@\n-docs\n+changed\n"
    run = trajectory([TESTS_BEFORE, EDIT_OK], final_patch=agent, fail_to_pass_ok=False)

    assert classify(run, gold, ["pkg/mod.py"]).category == "wrong_function"
