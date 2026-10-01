"""The agent's tools (S2): the only way the agent can look at or change the repository.

Every tool runs inside the instance's Docker sandbox and returns a ``ToolResult`` whose text is
shown to the model. Tools never raise on bad input from the model; they return ``ok=False`` with
an explanation, because a model's mistake is information it can recover from.
"""

from __future__ import annotations

import posixpath
from dataclasses import dataclass

from patchpilot.benchmarks.base import BenchmarkInstance, is_resolved, run_instance_tests
from patchpilot.sandbox import DockerSandbox, TestRunResult

MAX_LIST = 400
MAX_READ_LINES = 400
MAX_SEARCH_RESULTS = 50
TEST_OUTPUT_TAIL = 4000


@dataclass(frozen=True)
class ToolResult:
    ok: bool
    output: str


class Toolbox:
    """list_files, read_file, search_code, edit_file, run_tests and submit for one instance."""

    def __init__(self, sandbox: DockerSandbox, instance: BenchmarkInstance) -> None:
        self.sandbox = sandbox
        self.instance = instance
        self.last_tests: TestRunResult | None = None

    # ------------------------------------------------------------------ setup

    def prepare(self) -> ToolResult:
        """Reset the checkout and apply the patch that adds the failing test, if any."""
        self.sandbox.reset()
        if not self.instance.agent_test_patch:
            return ToolResult(True, "checkout ready")
        applied = self.sandbox.apply_patch(self.instance.agent_test_patch)
        return ToolResult(applied.ok, applied.output)

    # ------------------------------------------------------------------ reading

    def list_files(self, path: str = ".") -> ToolResult:
        """Tracked files under ``path`` (git ls-files), at most MAX_LIST of them."""
        safe = _safe_path(path)
        if safe is None:
            return ToolResult(False, f"invalid path: {path}")
        result = self.sandbox.exec(f"git ls-files -- {_quote(safe)} | head -n {MAX_LIST + 1}")
        files = result.output.splitlines()
        if not files:
            return ToolResult(False, f"no tracked files under {path}")
        text = "\n".join(files[:MAX_LIST])
        if len(files) > MAX_LIST:
            text += f"\n... (more than {MAX_LIST} files; list a subdirectory)"
        return ToolResult(True, text)

    def read_file(self, path: str, start: int = 1, end: int | None = None) -> ToolResult:
        """Lines ``start``..``end`` (1-based, inclusive) with line numbers."""
        safe = _safe_path(path)
        if safe is None:
            return ToolResult(False, f"invalid path: {path}")
        try:
            lines = self.sandbox.read_file(safe).splitlines()
        except FileNotFoundError:
            return ToolResult(False, f"file not found: {path}")
        start = max(1, start)
        end = min(len(lines), end if end is not None else start + MAX_READ_LINES - 1)
        end = min(end, start + MAX_READ_LINES - 1)
        if start > len(lines):
            return ToolResult(False, f"{path} has only {len(lines)} lines")
        body = "\n".join(f"{n:6d}  {lines[n - 1]}" for n in range(start, end + 1))
        header = f"{safe} (lines {start}-{end} of {len(lines)})"
        return ToolResult(True, f"{header}\n{body}")

    def search_code(self, query: str) -> ToolResult:
        """Fixed-string search over tracked files: ripgrep if the image has it, else git grep."""
        if not query.strip():
            return ToolResult(False, "empty query")
        q = _quote(query)
        command = (
            f"if command -v rg >/dev/null 2>&1; then "
            f"rg --no-heading -n -F -m 5 -- {q} . ; "
            f"else git grep -n -I -F -e {q} ; fi | head -n {MAX_SEARCH_RESULTS + 1}"
        )
        hits = self.sandbox.exec(command).output.splitlines()
        hits = [h.removeprefix("./") for h in hits if h.strip()]
        if not hits:
            return ToolResult(True, f"no matches for {query!r}")
        text = "\n".join(hits[:MAX_SEARCH_RESULTS])
        if len(hits) > MAX_SEARCH_RESULTS:
            text += f"\n... (more than {MAX_SEARCH_RESULTS} matches; refine the query)"
        return ToolResult(True, text)

    # ------------------------------------------------------------------ editing

    def edit_file(self, path: str, search: str, replace: str) -> ToolResult:
        """Replace one exact occurrence of ``search`` with ``replace``.

        The search block must match exactly once (an exact match is tried first, then a match
        that ignores indentation and trailing spaces). Python files must still compile;
        otherwise the edit is undone.
        """
        safe = _safe_path(path)
        if safe is None:
            return ToolResult(False, f"invalid path: {path}")
        if self._is_protected(safe):
            return ToolResult(False, f"{safe} is a test file and may not be edited")
        if not search.strip():
            return ToolResult(False, "the SEARCH block is empty")
        try:
            original = self.sandbox.read_file(safe)
        except FileNotFoundError:
            return ToolResult(False, f"file not found: {path}")

        updated, problem = apply_search_replace(original, search, replace)
        if updated is None:
            return ToolResult(False, f"{safe}: {problem}")
        self.sandbox.write_file(safe, updated)
        if safe.endswith(".py"):
            check = self.sandbox.exec(f"python -m py_compile {_quote(safe)}")
            if not check.ok:
                self.sandbox.write_file(safe, original)
                return ToolResult(False, f"edit undone, {safe} no longer compiles:\n{check.output}")
        return ToolResult(True, f"edited {safe}")

    # ------------------------------------------------------------------ verifying

    def run_tests(self) -> ToolResult:
        """Run the instance's target tests and summarise what passed and failed."""
        tests = run_instance_tests(self.instance, self.sandbox)
        self.last_tests = tests
        if self.instance.agent_test_patch:
            # SWE-bench's eval script restores the original test files when it finishes.
            self.sandbox.apply_patch(self.instance.agent_test_patch)
        return ToolResult(True, summarise_tests(self.instance, tests))

    def submit(self) -> ToolResult:
        """The candidate patch: every change except to protected (test) paths."""
        diff = self.sandbox.diff(exclude=self.instance.protected_paths)
        if not diff.strip():
            return ToolResult(False, "no changes to submit")
        return ToolResult(True, diff)

    # ------------------------------------------------------------------ helpers

    def _is_protected(self, path: str) -> bool:
        for protected in self.instance.protected_paths:
            if protected.endswith("/") and path.startswith(protected):
                return True
            if path == protected:
                return True
        return False


def summarise_tests(instance: BenchmarkInstance, tests: TestRunResult) -> str:
    f2p_ok, p2p_ok = is_resolved(instance, tests)
    lines: list[str] = []
    if tests.timed_out:
        lines.append("TIMED OUT before the tests finished.")
    if instance.fail_to_pass:
        target_failing = [t for t in instance.fail_to_pass if t not in tests.passed]
        broken = [t for t in instance.pass_to_pass if t not in tests.passed]
        lines.append(
            f"Target tests passing: {len(instance.fail_to_pass) - len(target_failing)}"
            f"/{len(instance.fail_to_pass)}"
        )
        lines += [f"  still failing: {t}" for t in target_failing[:20]]
        if broken:
            lines.append(f"Previously passing tests now failing: {len(broken)}")
            lines += [f"  broken: {t}" for t in broken[:20]]
    else:
        lines.append(f"Passed: {len(tests.passed)}  Failed: {len(tests.failed)}")
        lines += [f"  failing: {t}" for t in tests.failed[:20]]
    lines.append("ALL TESTS PASS." if f2p_ok and p2p_ok else "Tests are not passing yet.")
    lines.append("--- end of test output ---")
    lines.append(tests.output[-TEST_OUTPUT_TAIL:])
    return "\n".join(lines)


def apply_search_replace(original: str, search: str, replace: str) -> tuple[str | None, str]:
    """Return ``(new_text, "")`` or ``(None, reason)``."""
    count = original.count(search)
    if count == 1:
        return original.replace(search, replace, 1), ""
    if count > 1:
        return None, f"the SEARCH block matches {count} places; include more lines"

    # Fallback: compare line by line, ignoring indentation and trailing whitespace.
    file_lines = original.splitlines(keepends=True)
    search_lines = [line.strip() for line in search.strip("\n").splitlines()]
    n = len(search_lines)
    matches = [
        i
        for i in range(len(file_lines) - n + 1)
        if [line.strip() for line in file_lines[i : i + n]] == search_lines
    ]
    if len(matches) != 1:
        if not matches:
            return None, "the SEARCH block was not found; copy the lines exactly from read_file"
        return None, f"the SEARCH block matches {len(matches)} places; include more lines"
    i = matches[0]
    indent = _reindent(file_lines[i], search.strip("\n").splitlines()[0])
    new_block = "".join(
        indent + line + "\n" if line.strip() else "\n" for line in replace.strip("\n").splitlines()
    )
    return "".join(file_lines[:i]) + new_block + "".join(file_lines[i + n :]), ""


def _reindent(file_line: str, search_line: str) -> str:
    """Indentation to add so the model's block lines up with the file."""
    file_indent = file_line[: len(file_line) - len(file_line.lstrip())]
    search_indent = search_line[: len(search_line) - len(search_line.lstrip())]
    if file_indent.startswith(search_indent):
        return file_indent[len(search_indent) :]
    return ""


def _safe_path(path: str) -> str | None:
    """Normalise a repo-relative path; reject absolute paths and escapes from the repo."""
    path = path.strip().removeprefix("./") or "."
    if path.startswith("/") or "\x00" in path:
        return None
    normal = posixpath.normpath(path)
    if normal == ".." or normal.startswith("../"):
        return None
    return normal


def _quote(value: str) -> str:
    return "'" + value.replace("'", "'\\''") + "'"
