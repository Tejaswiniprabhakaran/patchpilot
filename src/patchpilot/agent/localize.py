"""Fault localization strategies: which files should the agent look at?

``LLMSearchLocalizer`` is the baseline used by B0 and E2 ("LLM search only"): the model proposes
identifiers, the agent searches the repository for them, and the model ranks the files found.
The trained ranker (Phase 3, A1) implements the same ``Localizer`` interface.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Protocol

from patchpilot.agent import prompts
from patchpilot.agent.trajectory import Timer, Trajectory
from patchpilot.benchmarks import BenchmarkInstance
from patchpilot.llm import LLMClient, Message
from patchpilot.tools import Toolbox

MAX_CANDIDATES = 30
MAX_PROMPT_TEST_OUTPUT = 3000
_PY_PATH = re.compile(r"(?<![\w/.-])((?:[\w.-]+/)*[\w.-]+\.py)\b")
_IDENTIFIER = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]{3,}\b")


@dataclass
class Localization:
    files: list[str]
    keywords: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)


class Localizer(Protocol):
    name: str

    def localize(
        self,
        instance: BenchmarkInstance,
        tools: Toolbox,
        test_summary: str,
        trajectory: Trajectory,
    ) -> Localization: ...


def is_test_path(path: str) -> bool:
    parts = path.lower().split("/")
    name = parts[-1]
    return (
        any(p in ("test", "tests", "testing", "testcases", "python_testcases") for p in parts[:-1])
        or name.startswith("test_")
        or name.endswith("_test.py")
        or name == "conftest.py"
    )


def tracked_python_files(tools: Toolbox) -> list[str]:
    out = tools.sandbox.exec("git ls-files -- '*.py'", truncate=False).output
    return [line for line in out.splitlines() if line.strip()]


def extract_json(text: str) -> dict[str, Any]:
    """First JSON object in a model reply (models often wrap it in prose or code fences)."""
    start = text.find("{")
    while start != -1:
        depth = 0
        for end in range(start, len(text)):
            if text[end] == "{":
                depth += 1
            elif text[end] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        value = json.loads(text[start : end + 1])
                    except json.JSONDecodeError:
                        break
                    return value if isinstance(value, dict) else {}
        start = text.find("{", start + 1)
    return {}


class LLMSearchLocalizer:
    """Baseline localization: model-proposed keywords + code search + model ranking."""

    name = "llm_search"

    def __init__(self, llm: LLMClient, top_k: int = 3) -> None:
        self.llm = llm
        self.top_k = top_k

    def localize(
        self,
        instance: BenchmarkInstance,
        tools: Toolbox,
        test_summary: str,
        trajectory: Trajectory,
    ) -> Localization:
        tests_text = test_summary[-MAX_PROMPT_TEST_OUTPUT:]
        all_files = tracked_python_files(tools)
        known = set(all_files)
        layout = sorted({"/".join(f.split("/")[:2]) for f in all_files})[:80]

        # 1. Ask the model for identifiers and suspected files.
        reply = self._ask(
            trajectory,
            "localize_keywords",
            prompts.LOCALIZE_KEYWORDS.format(
                repo=instance.repo,
                problem=instance.problem_statement,
                tests=tests_text,
                layout="\n".join(layout),
            ),
        )
        keywords = [str(k) for k in reply.get("keywords", []) if str(k).strip()][:5]
        suggested = [str(f).strip().removeprefix("./") for f in reply.get("files", [])][:5]

        # 2. Collect candidates with the reason each one was found.
        reasons: dict[str, list[str]] = {}

        def add(path: str, reason: str) -> None:
            if path in known and not is_test_path(path) and path not in instance.protected_paths:
                reasons.setdefault(path, []).append(reason)

        for path in _PY_PATH.findall(test_summary):
            add(path.removeprefix("/testbed/"), "appears in the failing test output")
        for path in suggested:
            add(path, "suggested by the model")
        hits: Counter[str] = Counter()
        for keyword in keywords:
            with Timer() as timer:
                result = tools.search_code(keyword)
            trajectory.add(
                "tool", "search_code", {"query": keyword}, result.output, result.ok, timer.elapsed
            )
            for line in result.output.splitlines():
                path = line.split(":", 1)[0]
                if path.endswith(".py"):
                    hits[path] += 1
        for path, count in hits.most_common():
            add(path, f"{count} search hit(s)")

        candidates = list(reasons)[:MAX_CANDIDATES]
        if len(candidates) <= self.top_k:
            files = candidates
        else:
            # 3. Let the model rank the candidates.
            listing = "\n".join(f"- {p}: {'; '.join(reasons[p])}" for p in candidates)
            ranked = self._ask(
                trajectory,
                "localize_rank",
                prompts.LOCALIZE_RANK.format(
                    repo=instance.repo,
                    problem=instance.problem_statement,
                    tests=tests_text,
                    candidates=listing,
                ),
            )
            chosen = [str(f).strip() for f in ranked.get("files", []) if str(f).strip() in reasons]
            files = list(dict.fromkeys(chosen + candidates))[: self.top_k]

        localization = Localization(
            files=files,
            keywords=keywords,
            details={"candidates": candidates, "reasons": reasons},
        )
        trajectory.add(
            "note", "localization", {"localizer": self.name}, "\n".join(files), bool(files)
        )
        return localization

    def _ask(self, trajectory: Trajectory, name: str, prompt: str) -> dict[str, Any]:
        messages = [Message("user", prompt)]
        completion = self.llm.complete(messages, max_tokens=512)
        trajectory.add(
            "llm",
            name,
            {"prompt": prompt},
            completion.text,
            duration_s=completion.latency_s,
            prompt_tokens=completion.prompt_tokens,
            completion_tokens=completion.completion_tokens,
        )
        return extract_json(completion.text)


def keywords_from_text(text: str, limit: int = 20) -> list[str]:
    """Identifiers worth searching for, e.g. function names in a traceback."""
    seen: dict[str, None] = {}
    for word in _IDENTIFIER.findall(text):
        if word not in _STOPWORDS:
            seen.setdefault(word, None)
    return list(seen)[:limit]


_STOPWORDS = {
    "self",
    "None",
    "True",
    "False",
    "return",
    "assert",
    "AssertionError",
    "Traceback",
    "File",
    "line",
    "def",
    "class",
    "import",
    "from",
    "test",
    "tests",
    "testbed",
    "PASSED",
    "FAILED",
    "ERROR",
    "python",
}
