"""Why did an unresolved run fail? Rule-based failure classifier (A5).

The rules read a run's trajectory and compare the agent's final patch with the developers' gold
patch. Rules are tried in order and the first match wins:

1. environment        the run crashed (Docker, model server) or a model call stalled
2. patch_invalid      no attempt produced an edit that applied (no blocks, SEARCH not found,
                      edit undone because the file stopped compiling)
3. wrong_file         the final patch edits none of the files the gold patch edits
4. breaks_other_tests the target tests pass but previously passing tests now fail
5. wrong_function     right file, but the edited lines are nowhere near the gold edit
6. incomplete_fix     edits overlap the gold region but the target tests still fail
7. out_of_attempts    anything left after the last attempt

``overfitting`` (special-casing the test inputs) cannot be recognised by rules; the LLM judge
(``judge.py``) may assign it, and may overturn the three last, least certain rule categories.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from patchpilot.evaluation.infra import STALL_S
from patchpilot.localization.patches import edited_lines

CATEGORIES = [
    "environment",
    "patch_invalid",
    "wrong_file",
    "breaks_other_tests",
    "wrong_function",
    "incomplete_fix",
    "out_of_attempts",
    "overfitting",
]
DESCRIPTIONS = {
    "environment": "Timeout or environment error (crash, model-server stall)",
    "patch_invalid": "Patch does not apply / syntax error / no edit produced",
    "wrong_file": "Wrong file localized",
    "breaks_other_tests": "Patch breaks previously passing tests",
    "wrong_function": "Right file, wrong location (function or lines)",
    "incomplete_fix": "Incomplete fix (right place, tests still fail)",
    "out_of_attempts": "Ran out of attempts",
    "overfitting": "Overfitting to the test (special-cases test inputs)",
}
UNCERTAIN = {"wrong_function", "incomplete_fix", "out_of_attempts"}
NEAR_LINES = 3  # an edit within this many lines of a gold edit counts as the same region


@dataclass
class Classification:
    instance_id: str
    run_id: str
    category: str
    reason: str
    source: str = "rules"  # "rules" or "judge"
    evidence: dict[str, Any] = field(default_factory=dict)


def _regions(diff: str) -> dict[str, set[int]]:
    return {path: edit.lines for path, edit in edited_lines(diff).items()}


_HUNK_HEADER = re.compile(r"^@@ -(\d+)(?:,\d+)? \+\d+(?:,\d+)? @@")


def code_regions(diff: str) -> dict[str, set[int]]:
    """Original-file lines a diff changes, ignoring blank lines, comments and docstrings.

    QuixBugs reference solutions carry no docstrings, so their gold patches also "delete" each
    program's docstring; those lines say nothing about where the bug is.
    """
    regions: dict[str, set[int]] = {}
    path: str | None = None
    line = 0
    in_string = False
    for raw in diff.splitlines():
        if raw.startswith("+++ "):
            target = raw[4:].strip()
            path = None if target == "/dev/null" else target.removeprefix("b/")
            in_string = False
            continue
        if raw.startswith("--- "):
            continue
        header = _HUNK_HEADER.match(raw)
        if header:
            line = int(header.group(1))
            in_string = False
            continue
        if path is None or not raw or raw[0] not in " -+":
            continue
        marker, text = raw[0], raw[1:]
        if marker == "+":
            if text.strip() and not in_string and not text.strip().startswith("#"):
                regions.setdefault(path, set()).add(max(line - 1, 1))
            continue
        quotes = text.count('"""') + text.count("'''")
        is_doc = in_string or quotes > 0
        if quotes % 2 == 1:
            in_string = not in_string
        if marker == "-" and text.strip() and not is_doc and not text.strip().startswith("#"):
            regions.setdefault(path, set()).add(line)
        line += 1
    return regions


def _near(a: Iterable[int], b: Iterable[int], tolerance: int = NEAR_LINES) -> bool:
    bs = sorted(b)
    return any(abs(x - y) <= tolerance for x in a for y in bs)


def classify(trajectory: dict[str, Any], gold_patch: str, gold_files: list[str]) -> Classification:
    """Classify one unresolved run. ``trajectory`` is a saved Trajectory dict."""
    result = trajectory.get("result", {})
    steps = trajectory.get("steps", [])
    base = {"instance_id": trajectory["instance_id"], "run_id": trajectory["run_id"]}
    if result.get("resolved"):
        raise ValueError("classify() is for unresolved runs")

    slowest = max((s["duration_s"] for s in steps if s["kind"] == "llm"), default=0.0)
    if result.get("error") or slowest > STALL_S:
        why = result.get("error") or f"a model call took {slowest:.0f} s"
        return Classification(**base, category="environment", reason=why)

    edits = [s for s in steps if s["name"] == "edit_file"]
    applied_edits = [s for s in edits if s["ok"]]
    final_patch = result.get("final_patch") or ""
    if not applied_edits or not final_patch.strip():
        problems = [
            s["output"][:120]
            for s in steps
            if s["name"] in ("edit_file", "no_edits") and not s["ok"]
        ]
        return Classification(
            **base,
            category="patch_invalid",
            reason=f"no attempt produced an applied edit ({len(problems)} failed edit steps)",
            evidence={"examples": problems[:3]},
        )

    agent = _regions(final_patch)
    gold = code_regions(gold_patch)
    touched_gold = [p for p in agent if p in gold_files]
    evidence = {
        "localized_files": result.get("localized_files", []),
        "gold_files": gold_files,
        "patched_files": sorted(agent),
    }
    if not touched_gold:
        return Classification(
            **base,
            category="wrong_file",
            reason="the final patch edits none of the gold files",
            evidence=evidence,
        )

    if result.get("fail_to_pass_ok") and result.get("pass_to_pass_ok") is False:
        return Classification(
            **base,
            category="breaks_other_tests",
            reason="target tests pass but previously passing tests fail",
            evidence=evidence,
        )

    overlap = any(_near(agent[p], gold.get(p, set())) for p in touched_gold)
    if not overlap:
        return Classification(
            **base,
            category="wrong_function",
            reason=f"edits in {touched_gold} are more than {NEAR_LINES} lines from every gold edit",
            evidence=evidence,
        )

    # Right region, still failing: did any attempt make progress over the buggy code?
    test_runs = [s for s in steps if s["name"] == "run_tests"]
    initial = passing_tests(test_runs[0]["output"]) if test_runs else None
    best = max((passing_tests(s["output"]) or 0 for s in test_runs[1:]), default=0)
    attempts = result.get("attempts_used", 0)
    max_attempts = trajectory.get("config", {}).get("agent", {}).get("max_attempts", attempts)
    evidence |= {"passing_before": initial, "best_passing_after": best, "attempts_used": attempts}
    if initial is not None and best > initial:
        return Classification(
            **base,
            category="incomplete_fix",
            reason=f"edited the gold region; passing tests rose from {initial} to {best}, not all",
            evidence=evidence,
        )
    if attempts >= max_attempts:
        return Classification(
            **base,
            category="out_of_attempts",
            reason=f"edited the gold region in {attempts} attempt(s); no extra test passed",
            evidence=evidence,
        )
    return Classification(
        **base,
        category="incomplete_fix",
        reason="edited the gold region but the target tests still fail",
        evidence=evidence,
    )


_TARGET = re.compile(r"Target tests passing: (\d+)/\d+")
_PASSED = re.compile(r"Passed: (\d+)\s+Failed: \d+")


def passing_tests(summary: str) -> int | None:
    """Passing-test count from a run_tests summary written by ``tools.summarise_tests``."""
    match = _TARGET.search(summary) or _PASSED.search(summary)
    return int(match.group(1)) if match else None


def cohen_kappa(a: list[str], b: list[str]) -> float:
    """Agreement between two labelings beyond what chance would give (1 = perfect, 0 = chance)."""
    if len(a) != len(b) or not a:
        raise ValueError("need two equally long, non-empty label lists")
    n = len(a)
    observed = sum(x == y for x, y in zip(a, b, strict=True)) / n
    labels = set(a) | set(b)
    expected = sum((a.count(c) / n) * (b.count(c) / n) for c in labels)
    if expected == 1:
        return 1.0
    return (observed - expected) / (1 - expected)
