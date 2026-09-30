"""Real Docker run on one QuixBugs program. Run with: pytest -m integration"""

import pytest

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def gcd_instance():  # type: ignore[no-untyped-def]
    docker = pytest.importorskip("docker")
    try:
        docker.from_env().ping()
    except Exception:
        pytest.skip("Docker daemon not available")
    from patchpilot.benchmarks import quixbugs

    quixbugs.ensure_downloaded()
    quixbugs.build_image()
    return quixbugs.load_instance("gcd")


def test_buggy_gcd_fails_and_gold_patch_fixes_it(gcd_instance) -> None:  # type: ignore[no-untyped-def]
    from patchpilot.benchmarks import evaluate_patch

    with gcd_instance.sandbox() as box:
        before = box.run_tests(gcd_instance.test_command)
        fixed = evaluate_patch(gcd_instance, gcd_instance.gold_patch, sandbox=box)

    assert before.failed and not before.all_passed
    assert fixed.applied and fixed.resolved
    assert len(fixed.tests.passed) == len(before.statuses)


def test_sandbox_has_no_network(gcd_instance) -> None:  # type: ignore[no-untyped-def]
    with gcd_instance.sandbox() as box:
        result = box.exec(
            "python -c \"import socket; socket.create_connection(('1.1.1.1', 53), timeout=3)\""
        )

    assert not result.ok
    assert "Network is unreachable" in result.output or "Errno" in result.output


def test_runaway_command_is_killed_at_the_time_limit(gcd_instance) -> None:  # type: ignore[no-untyped-def]
    with gcd_instance.sandbox() as box:
        result = box.exec("sleep 30", timeout_s=2)

    assert result.timed_out
    assert result.duration_s < 10


def test_bad_patch_leaves_tree_untouched(gcd_instance) -> None:  # type: ignore[no-untyped-def]
    bad = "--- a/python_programs/gcd.py\n+++ b/python_programs/gcd.py\n@@ -1,1 +1,1 @@\n-nope\n+x\n"
    with gcd_instance.sandbox() as box:
        result = box.apply_patch(bad)
        diff = box.diff()

    assert not result.ok
    assert diff.strip() == ""
