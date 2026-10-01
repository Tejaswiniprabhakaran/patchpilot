"""Gold-patch sanity check.

Before trusting any agent result on a benchmark instance we verify the instance itself:
the target tests must fail on the buggy code and pass once the reference ("gold") patch is
applied. An instance that fails this check cannot tell a good fix from a bad one.
"""

from __future__ import annotations

from typing import Any

from patchpilot.benchmarks.base import (
    BenchmarkInstance,
    evaluate_patch,
    is_resolved,
    run_instance_tests,
)
from patchpilot.sandbox import DockerSandbox


def check_instance(
    instance: BenchmarkInstance, sandbox: DockerSandbox | None = None
) -> dict[str, Any]:
    """Run the target tests before and after the gold patch. Returns one JSON-able record."""
    own_sandbox = sandbox is None
    box = sandbox or instance.sandbox()
    if own_sandbox:
        box.start()
    try:
        box.reset()
        if instance.test_patch:
            box.apply_patch(instance.test_patch)
        before = run_instance_tests(instance, box)
        after = evaluate_patch(instance, instance.gold_patch, sandbox=box)
    finally:
        if own_sandbox:
            box.stop()

    buggy_resolved = all(is_resolved(instance, before))
    return {
        "benchmark": instance.benchmark,
        "instance_id": instance.instance_id,
        "image": instance.image,
        "buggy_fails": not buggy_resolved,
        "buggy_passed": len(before.passed),
        "buggy_failed": len(before.failed),
        "buggy_timed_out": before.timed_out,
        "gold_applied": after.applied,
        "gold_resolved": after.resolved,
        "gold_passed": len(after.tests.passed),
        "gold_failed": after.tests.failed,
        "gold_timed_out": after.tests.timed_out,
        "gold_duration_s": round(after.tests.duration_s, 2),
        "valid": (not buggy_resolved) and after.resolved,
    }
