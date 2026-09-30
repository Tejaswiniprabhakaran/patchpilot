from patchpilot.sandbox import TestStatus, parse_pytest_summary

PYTEST_OUTPUT = """\
============================= test session starts ==============================
collected 5 items

tests/test_a.py ..F.s                                                    [100%]

=========================== short test summary info ============================
PASSED tests/test_a.py::test_one
PASSED tests/test_a.py::test_param[a b]
SKIPPED [1] tests/test_a.py:30: needs network
FAILED tests/test_a.py::test_three - AssertionError: assert 1 == 2
ERROR tests/test_b.py - ModuleNotFoundError: No module named 'x'
========================= 1 failed, 2 passed, 1 skipped =========================
"""


def test_parses_each_status() -> None:
    statuses = parse_pytest_summary(PYTEST_OUTPUT)

    assert statuses == {
        "tests/test_a.py::test_one": TestStatus.PASSED,
        "tests/test_a.py::test_param[a b]": TestStatus.PASSED,
        "tests/test_a.py:30": TestStatus.SKIPPED,
        "tests/test_a.py::test_three": TestStatus.FAILED,
        "tests/test_b.py": TestStatus.ERROR,
    }


def test_output_without_summary_gives_no_statuses() -> None:
    assert parse_pytest_summary("Killed\n") == {}


def test_ansi_colours_are_ignored() -> None:
    statuses = parse_pytest_summary("\x1b[32mPASSED\x1b[0m tests/test_a.py::test_one\n")

    assert statuses == {"tests/test_a.py::test_one": TestStatus.PASSED}


def test_worst_status_wins_when_a_test_is_reported_twice() -> None:
    output = "PASSED t.py::test_x\nERROR t.py::test_x - teardown failed\n"

    assert parse_pytest_summary(output) == {"t.py::test_x": TestStatus.ERROR}
