"""Agent loop tests with a scripted model and an in-memory sandbox."""

from __future__ import annotations

from tests.fakes import BUGGY, FakeSandbox, make_instance

from patchpilot.agent import Agent, AgentConfig, LLMSearchLocalizer
from patchpilot.llm import ScriptedClient

LOCATE = '{"keywords": ["add"], "files": ["pkg/mod.py"]}'
EDIT = "pkg/mod.py\n<<<<<<< SEARCH\n    return a - b\n=======\n    return {new}\n>>>>>>> REPLACE\n"
GOOD = "Wrong operator.\n\n" + EDIT.format(new="a + b")
WRONG = "Try this.\n\n" + EDIT.format(new="b - a")
BAD_SEARCH = (
    "pkg/mod.py\n<<<<<<< SEARCH\n    return nothing\n=======\n    return a + b\n>>>>>>> REPLACE\n"
)


def run(
    replies: list[str], max_attempts: int = 3
) -> tuple[dict, list, FakeSandbox, ScriptedClient]:  # type: ignore[type-arg]
    box = FakeSandbox()
    llm = ScriptedClient(replies)
    agent = Agent(
        llm,
        LLMSearchLocalizer(llm, top_k=3),
        AgentConfig(max_attempts=max_attempts),
        sandbox_factory=lambda _instance: box,  # type: ignore[arg-type,return-value]
    )
    trajectory = agent.run(make_instance())
    return trajectory.result, trajectory.steps, box, llm


def test_first_attempt_fix_is_resolved_and_graded() -> None:
    result, steps, box, _ = run([LOCATE, GOOD])

    assert result["resolved"] is True
    assert result["attempts_used"] == 1
    assert result["localized_files"] == ["pkg/mod.py"]
    assert "a + b" in result["final_patch"]
    assert steps[-1].name == "evaluate"
    assert box.started and box.stopped
    assert result["llm_calls"] == 2


def test_failed_attempt_feeds_test_output_back_and_retry_succeeds() -> None:
    result, _, _, llm = run([LOCATE, WRONG, GOOD])

    assert result["resolved"] is True
    assert result["attempts_used"] == 2
    retry_prompt = llm.prompts[2][1].content
    assert "previous attempt (attempt 1) did not work" in retry_prompt
    assert "b - a" in retry_prompt  # the previous edit
    assert "FAILED" in retry_prompt  # the test feedback


def test_each_attempt_starts_from_original_code() -> None:
    # If attempt 2 started from attempt 1's code, the SEARCH for "a - b" would not match.
    result, _, _, _ = run([LOCATE, WRONG, GOOD])

    assert result["resolved"] is True


def test_edit_that_does_not_apply_is_reported_to_the_model() -> None:
    result, _, _, llm = run([LOCATE, BAD_SEARCH, GOOD])

    assert result["resolved"] is True
    assert "SEARCH block was not found" in llm.prompts[2][1].content


def test_retries_off_means_a_single_attempt() -> None:
    result, _, _, _ = run([LOCATE, WRONG], max_attempts=1)

    assert result["resolved"] is False
    assert result["attempts_used"] == 1
    assert "b - a" in result["final_patch"]  # best (unresolved) candidate is still submitted


def test_reply_without_edits_counts_as_an_attempt() -> None:
    result, steps, _, _ = run([LOCATE, "I am not sure.", "Still not sure."], max_attempts=2)

    assert result["resolved"] is False
    assert result["final_patch"] == ""
    assert result["applied"] is False
    assert sum(s.name == "no_edits" for s in steps) == 2


def test_environment_error_is_recorded_not_raised() -> None:
    box = FakeSandbox()

    def broken_start() -> None:
        raise RuntimeError("docker daemon gone")

    box.start = broken_start  # type: ignore[method-assign]
    llm = ScriptedClient([])
    agent = Agent(llm, LLMSearchLocalizer(llm), sandbox_factory=lambda _i: box)  # type: ignore[arg-type,return-value]

    trajectory = agent.run(make_instance())

    assert trajectory.result["resolved"] is False
    assert "docker daemon gone" in trajectory.result["error"]
    assert box.stopped


def test_long_files_are_trimmed_to_windows_around_keywords() -> None:
    filler = "".join(f"x{i} = {i}\n" for i in range(1000))
    agent = Agent(ScriptedClient([]), LLMSearchLocalizer(ScriptedClient([])))

    text = agent._trim("big.py", filler + BUGGY + filler, ["add"])

    assert "def add(a, b):" in text
    assert "excerpts" in text
    assert len(text.splitlines()) < 100
