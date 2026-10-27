"""LLM judge for failure analysis (A5): second opinion on the uncertain rule categories.

The rules are reliable for crashes, invalid patches, wrong files and broken tests. They are least
certain about *why* an edit in the right place still failed, and they cannot see overfitting at
all. For those runs a model reads the evidence and picks one category; an unparseable or invalid
answer leaves the rule label in place.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from patchpilot.agent.localize import extract_json
from patchpilot.analysis.failures import (
    CATEGORIES,
    DESCRIPTIONS,
    UNCERTAIN,
    Classification,
    classify,
)
from patchpilot.llm import LLMClient, Message

MAX_SECTION = 2500

PROMPT = """You are reviewing why an automated bug-fixing attempt FAILED (the tests did not pass).

## Bug report
{problem}

## The developers' correct fix
{gold}

## The agent's final patch
{patch}

## Test result of the agent's best attempt
{tests}

## Rule-based guess
{rule}: {reason}

Choose the single best category:
{categories}

Reply with JSON only: {{"category": "<one of the names above>", "reason": "<one sentence>"}}"""


def problem_text(trajectory: dict[str, Any]) -> str:
    """The bug report, recovered from the first repair prompt."""
    for step in trajectory.get("steps", []):
        prompt = str(step.get("input", {}).get("prompt", ""))
        if step["name"] == "repair" and "## Bug report" in prompt:
            return prompt.split("## Bug report", 1)[1].split("## Failing tests", 1)[0].strip()
    return "(not recorded)"


def last_tests(trajectory: dict[str, Any]) -> str:
    runs = [str(s["output"]) for s in trajectory.get("steps", []) if s["name"] == "run_tests"]
    return runs[-1] if runs else "(no test run recorded)"


def judge(
    rule: Classification, trajectory: dict[str, Any], gold_patch: str, llm: LLMClient
) -> Classification:
    categories = "\n".join(f"- {name}: {DESCRIPTIONS[name]}" for name in CATEGORIES)
    prompt = PROMPT.format(
        problem=problem_text(trajectory)[:MAX_SECTION],
        gold=gold_patch[:MAX_SECTION],
        patch=(trajectory.get("result", {}).get("final_patch") or "(no patch)")[:MAX_SECTION],
        tests=last_tests(trajectory)[-MAX_SECTION:],
        rule=rule.category,
        reason=rule.reason,
        categories=categories,
    )
    answer = llm.complete([Message("user", prompt)], max_tokens=200)
    verdict = extract_json(answer.text)
    category = str(verdict.get("category", "")).strip()
    if category not in CATEGORIES:
        return replace(rule, evidence=rule.evidence | {"judge_unparsed": answer.text[:300]})
    return replace(
        rule,
        category=category,
        reason=str(verdict.get("reason", "")).strip() or rule.reason,
        source="judge",
        evidence=rule.evidence | {"rule_category": rule.category},
    )


def classify_with_judge(
    trajectory: dict[str, Any], gold_patch: str, gold_files: list[str], llm: LLMClient | None
) -> Classification:
    """Rules first; the judge only reviews the uncertain categories (when a model is given)."""
    rule = classify(trajectory, gold_patch, gold_files)
    if llm is None or rule.category not in UNCERTAIN:
        return rule
    return judge(rule, trajectory, gold_patch, llm)
