"""Write and post the bot's pull-request comment (S4). Comments only: never pushes, never merges."""

from __future__ import annotations

import json
import urllib.request
from typing import Any

MARKER = "<!-- patchpilot-bot -->"
MAX_DIFF_CHARS = 20_000
MAX_TESTS_CHARS = 3_000


def format_comment(result: dict[str, Any], tests_before: str, tests_after: str, model: str) -> str:
    patch = (result.get("final_patch") or "").strip()
    resolved = bool(result.get("resolved"))
    lines = [MARKER, "### 🛠️ PatchPilot", ""]
    if resolved:
        lines.append(
            "The tests in this pull request fail. PatchPilot found a change that makes them pass "
            "in an isolated sandbox. **It has not been applied**; review it and apply it "
            "yourself if it is right."
        )
    elif patch:
        lines.append(
            "The tests in this pull request fail. PatchPilot's best attempt did **not** make every "
            "test pass; it is shown below as a starting point only."
        )
    else:
        lines.append(
            "The tests in this pull request fail. PatchPilot could not produce a fix this time."
        )
    suspected = ", ".join(f"`{f}`" for f in result.get("localized_files", [])) or "-"
    lines += [
        "",
        f"- Model: `{model}` · attempts used: {result.get('attempts_used', 0)} · "
        f"time: {round(result.get('wall_s') or 0)} s",
        f"- Files it suspected: {suspected}",
        "",
    ]
    if patch:
        lines += [
            "<details open><summary>Proposed patch</summary>",
            "",
            "```diff",
            patch[:MAX_DIFF_CHARS],
            "```",
            "",
            "</details>",
            "",
        ]
    lines += [
        "<details><summary>Test output before</summary>",
        "",
        "```",
        tests_before[-MAX_TESTS_CHARS:],
        "```",
        "",
        "</details>",
        "",
    ]
    if tests_after:
        lines += [
            "<details><summary>Test output with the patch</summary>",
            "",
            "```",
            tests_after[-MAX_TESTS_CHARS:],
            "```",
            "",
            "</details>",
            "",
        ]
    lines.append(
        "<sub>PatchPilot only comments. It never pushes commits or merges pull requests.</sub>"
    )
    return "\n".join(lines)


def post_comment(
    token: str, repo: str, number: int, body: str, api: str = "https://api.github.com"
) -> int:
    """Post an issue comment on the pull request. Returns the HTTP status code."""
    request = urllib.request.Request(
        f"{api}/repos/{repo}/issues/{number}/comments",
        data=json.dumps({"body": body}).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return int(response.status)
