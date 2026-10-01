"""Benchmark loaders: QuixBugs and SWE-bench Lite."""

from patchpilot.benchmarks.base import (
    BenchmarkInstance,
    PatchEvaluation,
    evaluate_patch,
    is_resolved,
    run_instance_tests,
)

__all__ = [
    "BenchmarkInstance",
    "PatchEvaluation",
    "evaluate_patch",
    "is_resolved",
    "run_instance_tests",
]
