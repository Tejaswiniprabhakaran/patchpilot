"""PatchPilot pull-request bot (S4): `python -m patchpilot.bot --test-command "pytest -rA"`.

Run from the root of a checked-out pull request (GitHub Actions does this). It builds a sandbox
image from the tracked files, runs the tests with the network off and, only if they fail, asks the
agent for a fix and posts it as a PR comment. It never pushes commits and never merges.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from patchpilot.agent import Agent, AgentConfig, LLMSearchLocalizer
from patchpilot.benchmarks import run_instance_tests
from patchpilot.bot.comment import format_comment, post_comment
from patchpilot.bot.local_repo import build_image, make_instance
from patchpilot.llm import LLMConfig, OpenAICompatibleClient
from patchpilot.tools import summarise_tests


def pull_request_context(event_path: str | None) -> dict[str, Any]:
    """Number, title and body of the pull request from the GitHub Actions event file."""
    if not event_path or not Path(event_path).exists():
        return {}
    event = json.loads(Path(event_path).read_text(encoding="utf-8"))
    pr = event.get("pull_request") or {}
    return {
        "number": pr.get("number"),
        "title": pr.get("title") or "",
        "body": pr.get("body") or "",
    }


def problem_statement(context: dict[str, Any], test_command: str) -> str:
    parts = []
    if context.get("title"):
        parts.append(f"Pull request: {context['title']}")
    if context.get("body"):
        parts.append(str(context["body"])[:3000])
    parts.append(
        f"The test command `{test_command}` fails on this pull request. "
        "Fix the source code (not the tests) so that the tests pass."
    )
    return "\n\n".join(parts)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-dir", type=Path, default=Path("."))
    parser.add_argument("--test-command", default="python -m pytest -rA -q -p no:cacheprovider")
    parser.add_argument("--model", default=os.environ.get("PATCHPILOT_LLM_MODEL", "gemma4:e4b"))
    parser.add_argument(
        "--base-url", default=os.environ.get("PATCHPILOT_LLM_BASE_URL", "http://localhost:11434/v1")
    )
    parser.add_argument("--max-attempts", type=int, default=2)
    parser.add_argument(
        "--protected", default="tests/", help="comma-separated paths the agent may not edit"
    )
    parser.add_argument("--repo", default=os.environ.get("GITHUB_REPOSITORY", "local/repo"))
    parser.add_argument("--pr", type=int, default=None)
    parser.add_argument(
        "--dry-run", action="store_true", help="print the comment instead of posting it"
    )
    args = parser.parse_args(argv)

    context = pull_request_context(os.environ.get("GITHUB_EVENT_PATH"))
    number = args.pr or context.get("number")
    sha = subprocess.run(
        ["git", "-C", str(args.repo_dir), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    image = build_image(args.repo_dir.resolve(), f"patchpilot/pr:{sha[:12]}")
    instance = make_instance(
        args.repo,
        sha,
        image,
        args.test_command,
        problem_statement(context, args.test_command),
        protected=tuple(p.strip() for p in args.protected.split(",") if p.strip()),
    )

    with instance.sandbox() as box:
        before = run_instance_tests(instance, box)
    tests_before = summarise_tests(instance, before)
    if before.all_passed:
        print("All tests pass; PatchPilot has nothing to do.")
        return 0
    print(tests_before)

    llm = OpenAICompatibleClient(
        LLMConfig(base_url=args.base_url, model=args.model, reasoning_effort="none")
    )
    agent = Agent(llm, LLMSearchLocalizer(llm), AgentConfig(max_attempts=args.max_attempts))
    trajectory = agent.run(instance, {"experiment": "bot", "repo": args.repo, "pr": number})
    trajectory.save(Path("runs"))
    after = next(
        (s["output"] for s in reversed(trajectory.to_dict()["steps"]) if s["name"] == "evaluate"),
        "",
    )
    body = format_comment(trajectory.result, tests_before, after, args.model)

    token = os.environ.get("GITHUB_TOKEN")
    if args.dry_run or not token or not number:
        print(body)
        return 0
    status = post_comment(token, args.repo, int(number), body)
    print(f"posted a comment on {args.repo}#{number} (HTTP {status})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
