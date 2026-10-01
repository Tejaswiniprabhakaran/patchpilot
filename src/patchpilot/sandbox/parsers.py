"""Turn raw test-runner output into per-test statuses."""

import re

from patchpilot.sandbox.models import TestStatus

# Lines of pytest's "short test summary info" section, produced by `pytest -rA`.
_SUMMARY_LINE = re.compile(r"^(PASSED|FAILED|ERROR|SKIPPED|XFAIL|XPASS)\s+(.+)$")
_SKIP_PREFIX = re.compile(r"^\[\d+\]\s+")
_ANSI = re.compile(r"\x1b\[[0-9;]*m")

_STATUS = {
    "PASSED": TestStatus.PASSED,
    "XPASS": TestStatus.PASSED,
    "FAILED": TestStatus.FAILED,
    "ERROR": TestStatus.ERROR,
    "SKIPPED": TestStatus.SKIPPED,
    "XFAIL": TestStatus.SKIPPED,
}


def parse_pytest_summary(output: str) -> dict[str, TestStatus]:
    """Parse the `-rA` short summary of a pytest run.

    Returns a mapping of test id (``path::name[param]``) to status. A test that appears more
    than once keeps its worst status, so a test that passed its call phase but errored in
    teardown counts as an error.
    """
    statuses: dict[str, TestStatus] = {}
    for raw in output.splitlines():
        match = _SUMMARY_LINE.match(_ANSI.sub("", raw).strip())
        if match is None:
            continue
        keyword, rest = match.groups()
        status = _STATUS[keyword]
        if keyword == "SKIPPED":
            # "SKIPPED [1] path/to/test.py:12: reason"
            test_id = _SKIP_PREFIX.sub("", rest).split(": ", 1)[0]
        else:
            # "FAILED path::name - AssertionError: ..."
            test_id = rest.split(" - ", 1)[0].strip()
        statuses[test_id] = _worst(statuses.get(test_id), status)
    return statuses


_SEVERITY = [TestStatus.SKIPPED, TestStatus.PASSED, TestStatus.FAILED, TestStatus.ERROR]


def _worst(current: TestStatus | None, new: TestStatus) -> TestStatus:
    if current is None:
        return new
    return max(current, new, key=_SEVERITY.index)
