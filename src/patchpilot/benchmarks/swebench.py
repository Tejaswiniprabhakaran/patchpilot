"""SWE-bench Lite: 300 real GitHub issues from 12 Python repositories.

The main evaluation set is a fixed, seeded random subset of 50 instances (see
``configs/swebench_lite_subset_50.json`` and ``make_subset``). All 300 can be loaded with
``load_instances()``.

We reuse the official harness for everything that decides correctness: the per-instance eval
script (which resets the test files, applies the test patch and runs the repository's own
test command) and the per-repository log parsers. Only the container itself is ours, so the
same network-off, resource-limited sandbox runs both the agent and the grading.
"""

from __future__ import annotations

import contextlib
import json
import random
import sys
import types
from collections.abc import Iterator
from functools import cache
from pathlib import Path
from typing import Any

from patchpilot.benchmarks.base import BenchmarkInstance
from patchpilot.sandbox import TestStatus
from patchpilot.sandbox.docker_sandbox import TestParser

NAME = "swebench-lite"
DATASET = "princeton-nlp/SWE-bench_Lite"
# Pinned dataset revision so the instance list can never change under us.
DATASET_REVISION = "6ec7bb89b9342f664a54a6e0a6ea6501d3437cc2"
SPLIT = "test"
IMAGE_NAMESPACE = "swebench"
SUBSET_FILE = Path("configs/swebench_lite_subset_50.json")
SUBSET_SEED = 42
SUBSET_SIZE = 50
EVAL_SCRIPT_PATH = "/eval.sh"
SHELL_PREFIX = "source /opt/miniconda3/bin/activate testbed"

_STATUS = {
    "PASSED": TestStatus.PASSED,
    "XFAIL": TestStatus.PASSED,  # the harness counts an expected failure as a pass
    "FAILED": TestStatus.FAILED,
    "ERROR": TestStatus.ERROR,
    "SKIPPED": TestStatus.SKIPPED,
}


def _harness() -> types.SimpleNamespace:
    """Import the official harness.

    ``swebench`` imports the Unix-only ``resource`` module at package import time. The parts we
    use (test specs, log parsers) never call it, so on Windows a stub module is registered
    first. See docs/decisions.md D6.
    """
    if sys.platform == "win32":
        sys.modules.setdefault("resource", types.ModuleType("resource"))
    from swebench.harness.constants import END_TEST_OUTPUT, START_TEST_OUTPUT
    from swebench.harness.log_parsers import MAP_REPO_TO_PARSER
    from swebench.harness.test_spec.test_spec import make_test_spec

    return types.SimpleNamespace(
        make_test_spec=make_test_spec,
        parsers=MAP_REPO_TO_PARSER,
        start=START_TEST_OUTPUT,
        end=END_TEST_OUTPUT,
    )


@cache
def _rows() -> dict[str, dict[str, Any]]:
    from datasets import load_dataset

    dataset = load_dataset(DATASET, split=SPLIT, revision=DATASET_REVISION)
    return {row["instance_id"]: dict(row) for row in dataset}


@cache
def _test_spec(instance_id: str) -> Any:
    return _harness().make_test_spec(_rows()[instance_id], namespace=IMAGE_NAMESPACE)


def _as_tuple(value: str | list[str]) -> tuple[str, ...]:
    return tuple(json.loads(value) if isinstance(value, str) else value)


def to_instance(row: dict[str, Any], spec: Any) -> BenchmarkInstance:
    return BenchmarkInstance(
        benchmark=NAME,
        instance_id=row["instance_id"],
        repo=row["repo"],
        base_commit=row["base_commit"],
        image=spec.instance_image_key,
        shell_prefix=SHELL_PREFIX,
        problem_statement=row["problem_statement"],
        test_command=f"bash {EVAL_SCRIPT_PATH}",
        fail_to_pass=_as_tuple(row["FAIL_TO_PASS"]),
        pass_to_pass=_as_tuple(row["PASS_TO_PASS"]),
        gold_patch=row["patch"],
        # The official eval script applies the test patch itself, so it is not applied twice.
        test_patch="",
        setup_files={EVAL_SCRIPT_PATH: spec.eval_script},
        log_parser="swebench",
        test_timeout_s=1800,
        memory="4g",
    )


def load_instance(instance_id: str) -> BenchmarkInstance:
    return to_instance(_rows()[instance_id], _test_spec(instance_id))


def load_instances() -> list[BenchmarkInstance]:
    return [load_instance(instance_id) for instance_id in sorted(_rows())]


def make_subset(
    instance_ids: list[str], size: int = SUBSET_SIZE, seed: int = SUBSET_SEED
) -> list[str]:
    """Seeded random sample, independent of the order the ids arrive in."""
    return sorted(random.Random(seed).sample(sorted(instance_ids), size))


def write_subset_file(path: Path = SUBSET_FILE) -> list[str]:
    ids = make_subset(list(_rows()))
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "dataset": DATASET,
        "revision": DATASET_REVISION,
        "split": SPLIT,
        "seed": SUBSET_SEED,
        "size": SUBSET_SIZE,
        "method": "random.Random(seed).sample(sorted(all_instance_ids), size), then sorted",
        "instance_ids": ids,
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8", newline="\n")
    return ids


def subset_ids(path: Path = SUBSET_FILE) -> list[str]:
    ids: list[str] = json.loads(path.read_text(encoding="utf-8"))["instance_ids"]
    return ids


def load_subset(path: Path = SUBSET_FILE) -> list[BenchmarkInstance]:
    return [load_instance(instance_id) for instance_id in subset_ids(path)]


def parse_eval_log(instance_id: str, log: str) -> dict[str, TestStatus]:
    """Parse the output of the official eval script with the repository's official parser."""
    harness = _harness()
    if harness.start not in log or harness.end not in log:
        return {}
    spec = _test_spec(instance_id)
    parser = harness.parsers[spec.repo]
    section = log.split(harness.start, 1)[1].split(harness.end, 1)[0]
    raw: dict[str, str] = parser(section, spec) or parser(log, spec)
    return {test: _STATUS[status] for test, status in raw.items() if status in _STATUS}


def parser_for(instance_id: str) -> TestParser:
    def parse(log: str) -> dict[str, TestStatus]:
        return parse_eval_log(instance_id, log)

    return parse


@contextlib.contextmanager
def pulled_image(image: str, prune: bool = True, client: Any = None) -> Iterator[str]:
    """Make sure ``image`` is present; remove it afterwards if we pulled it (decisions.md D5)."""
    import docker

    client = client or docker.from_env()
    pulled = False
    try:
        client.images.get(image)
    except docker.errors.ImageNotFound:
        client.images.pull(image)
        pulled = True
    try:
        yield image
    finally:
        if prune and pulled:
            with contextlib.suppress(docker.errors.APIError):
                client.images.remove(image, force=True)
