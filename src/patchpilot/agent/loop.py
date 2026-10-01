"""The agent loop (S2): reproduce, localize, read, edit, test, retry, submit.

    failing tests -> localize files -> read code -> propose edit -> run tests
                                             ^                         |
                                             +---- test feedback <-----+  (up to N attempts)

Each attempt starts from the original code, so a bad attempt never contaminates the next one;
the model sees its previous edit and why it failed. The best candidate is graded independently
on a fresh checkout with the benchmark's own resolution rule.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from typing import Any

from pydantic import BaseModel

from patchpilot.agent import prompts
from patchpilot.agent.edits import parse_edits
from patchpilot.agent.localize import Localization, Localizer, keywords_from_text
from patchpilot.agent.trajectory import Timer, Trajectory
from patchpilot.benchmarks import BenchmarkInstance, evaluate_patch, is_resolved
from patchpilot.llm import LLMClient, Message
from patchpilot.sandbox import DockerSandbox
from patchpilot.tools import Toolbox, ToolResult

CONTEXT_WINDOW = 40  # lines shown around each keyword hit in a long file


class AgentConfig(BaseModel):
    max_attempts: int = 3
    top_k_files: int = 3
    max_context_lines_per_file: int = 300
    max_wall_s: float = 3600.0


@dataclass
class Candidate:
    attempt: int
    diff: str
    applied: bool
    resolved: bool = False
    target_passing: int = 0
    broken: int = 0

    def score(self) -> tuple[bool, int, int]:
        return (self.resolved, self.target_passing, -self.broken)


class Agent:
    def __init__(
        self,
        llm: LLMClient,
        localizer: Localizer,
        config: AgentConfig | None = None,
        sandbox_factory: Callable[[BenchmarkInstance], DockerSandbox] | None = None,
    ) -> None:
        self.llm = llm
        self.localizer = localizer
        self.config = config or AgentConfig()
        self.sandbox_factory = sandbox_factory or (lambda instance: instance.sandbox())

    # ------------------------------------------------------------------ public

    def run(
        self, instance: BenchmarkInstance, run_config: dict[str, Any] | None = None
    ) -> Trajectory:
        trajectory = Trajectory(
            run_id=f"{instance.instance_id}-{uuid.uuid4().hex[:8]}",
            benchmark=instance.benchmark,
            instance_id=instance.instance_id,
            config={"agent": self.config.model_dump(), "localizer": self.localizer.name}
            | (run_config or {}),
        )
        started = time.monotonic()
        sandbox = self.sandbox_factory(instance)
        try:
            sandbox.start()
            self._run(instance, Toolbox(sandbox, instance), trajectory, started)
        except Exception as exc:  # environment failures are results too (failure analysis)
            trajectory.add("note", "error", {}, f"{type(exc).__name__}: {exc}", ok=False)
            trajectory.result.setdefault("resolved", False)
            trajectory.result["error"] = f"{type(exc).__name__}: {exc}"
        finally:
            sandbox.stop()
        trajectory.result["wall_s"] = round(time.monotonic() - started, 2)
        usage = getattr(self.llm, "usage", None)
        if usage is not None:
            trajectory.result.update(usage.totals())
        return trajectory

    # ------------------------------------------------------------------ steps

    def _run(
        self, instance: BenchmarkInstance, tools: Toolbox, trajectory: Trajectory, started: float
    ) -> None:
        self._tool(trajectory, "prepare", {}, tools.prepare)
        initial = self._tool(trajectory, "run_tests", {"phase": "reproduce"}, tools.run_tests)
        localization = self.localizer.localize(instance, tools, initial.output, trajectory)
        context = self._context(tools, localization, initial.output, trajectory)

        candidates: list[Candidate] = []
        previous: tuple[str, str] | None = None
        for attempt in range(1, self.config.max_attempts + 1):
            if time.monotonic() - started > self.config.max_wall_s:
                trajectory.add("note", "budget", {}, "wall-clock budget exhausted", ok=False)
                break
            if attempt > 1:
                self._tool(trajectory, "prepare", {"attempt": attempt}, tools.prepare)
            candidate, previous = self._attempt(
                instance, tools, trajectory, attempt, initial.output, context, previous
            )
            candidates.append(candidate)
            if candidate.resolved:
                break

        best = max((c for c in candidates if c.diff), key=Candidate.score, default=None)
        trajectory.result.update(
            {
                "localized_files": localization.files,
                "attempts_used": len(candidates),
                "best_attempt": best.attempt if best else None,
                "final_patch": best.diff if best else "",
            }
        )
        if best is None:
            trajectory.result.update({"resolved": False, "applied": False})
            return
        with Timer() as timer:
            evaluation = evaluate_patch(instance, best.diff, sandbox=tools.sandbox)
        trajectory.add(
            "tool",
            "evaluate",
            {"attempt": best.attempt},
            evaluation.tests.output,
            evaluation.resolved,
            timer.elapsed,
            fail_to_pass_ok=evaluation.fail_to_pass_ok,
            pass_to_pass_ok=evaluation.pass_to_pass_ok,
        )
        trajectory.result.update(
            {
                "resolved": evaluation.resolved,
                "applied": evaluation.applied,
                "fail_to_pass_ok": evaluation.fail_to_pass_ok,
                "pass_to_pass_ok": evaluation.pass_to_pass_ok,
            }
        )

    def _attempt(
        self,
        instance: BenchmarkInstance,
        tools: Toolbox,
        trajectory: Trajectory,
        attempt: int,
        test_output: str,
        context: str,
        previous: tuple[str, str] | None,
    ) -> tuple[Candidate, tuple[str, str]]:
        user = prompts.REPAIR.format(
            problem=instance.problem_statement, tests=test_output[-4000:], context=context
        )
        if previous is not None:
            user += "\n\n" + prompts.RETRY.format(
                attempt=attempt - 1, previous_edit=previous[0], feedback=previous[1][-4000:]
            )
        messages = [Message("system", prompts.SYSTEM), Message("user", user)]
        completion = self.llm.complete(messages)
        trajectory.add(
            "llm",
            "repair",
            {"attempt": attempt, "prompt": user},
            completion.text,
            duration_s=completion.latency_s,
            prompt_tokens=completion.prompt_tokens,
            completion_tokens=completion.completion_tokens,
            finish_reason=completion.finish_reason,
            reasoning=completion.reasoning,
        )

        edits = parse_edits(completion.text)
        if not edits:
            if completion.finish_reason == "length":
                feedback = (
                    "Your answer was cut off by the length limit before any edit block. "
                    "Keep the explanation short and give the edit blocks first."
                )
            else:
                feedback = (
                    "No edit blocks were found in your answer. Use the exact SEARCH/REPLACE format."
                )
            trajectory.add("note", "no_edits", {"attempt": attempt}, feedback, ok=False)
            return Candidate(attempt, "", applied=False), (completion.text[-2000:], feedback)

        for edit in edits:
            result = self._tool(
                trajectory,
                "edit_file",
                {
                    "attempt": attempt,
                    "path": edit.path,
                    "search": edit.search,
                    "replace": edit.replace,
                },
                partial(tools.edit_file, edit.path, edit.search, edit.replace),
            )
            if not result.ok:
                return Candidate(attempt, "", applied=False), (
                    completion.text[-2000:],
                    result.output,
                )

        summary = self._tool(trajectory, "run_tests", {"attempt": attempt}, tools.run_tests)
        submitted = self._tool(trajectory, "submit", {"attempt": attempt}, tools.submit)
        diff = submitted.output if submitted.ok else ""
        tests = tools.last_tests
        f2p, p2p = is_resolved(instance, tests) if tests else (False, False)
        candidate = Candidate(
            attempt,
            diff,
            applied=True,
            resolved=f2p and p2p,
            target_passing=_count_passing(instance, tests),
            broken=_count_broken(instance, tests),
        )
        return candidate, (diff, summary.output)

    def _context(
        self, tools: Toolbox, localization: Localization, test_output: str, trajectory: Trajectory
    ) -> str:
        keywords = localization.keywords + keywords_from_text(test_output)
        blocks = []
        for path in localization.files:
            with Timer() as timer:
                try:
                    content = tools.sandbox.read_file(path)
                except FileNotFoundError:
                    content = None
            trajectory.add(
                "tool",
                "read_file",
                {"path": path},
                f"{len(content.splitlines())} lines" if content is not None else "file not found",
                content is not None,
                timer.elapsed,
            )
            if content is not None:
                blocks.append(self._trim(path, content, keywords))
        return "\n\n".join(blocks) if blocks else "(no source files could be read)"

    def _trim(self, path: str, content: str, keywords: list[str]) -> str:
        """Whole file if short; otherwise windows around lines mentioning a keyword."""
        lines = [f"{n:6d}  {line}" for n, line in enumerate(content.splitlines(), start=1)]
        limit = self.config.max_context_lines_per_file
        if len(lines) <= limit:
            return f"### {path}\n" + "\n".join(lines)
        keep: set[int] = set()
        for index, line in enumerate(lines):
            if any(k in line for k in keywords):
                keep.update(range(max(0, index - CONTEXT_WINDOW // 2), index + CONTEXT_WINDOW // 2))
            if len(keep) >= limit:
                break
        if not keep:
            keep = set(range(limit))
        shown, last = [], -2
        for index in sorted(i for i in keep if i < len(lines))[:limit]:
            if index != last + 1:
                shown.append("   ...")
            shown.append(lines[index])
            last = index
        return f"### {path} (excerpts; line numbers on the left)\n" + "\n".join(shown)

    @staticmethod
    def _tool(
        trajectory: Trajectory, name: str, args: dict[str, Any], call: Callable[[], ToolResult]
    ) -> ToolResult:
        with Timer() as timer:
            result = call()
        trajectory.add("tool", name, args, result.output, result.ok, timer.elapsed)
        return result


def _count_passing(instance: BenchmarkInstance, tests: Any) -> int:
    if tests is None:
        return 0
    if instance.fail_to_pass:
        return sum(1 for t in instance.fail_to_pass if t in tests.passed)
    return len(tests.passed)


def _count_broken(instance: BenchmarkInstance, tests: Any) -> int:
    if tests is None:
        return 0
    if instance.pass_to_pass:
        return sum(1 for t in instance.pass_to_pass if t not in tests.passed)
    return len(tests.failed)
