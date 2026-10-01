import json
import types
from pathlib import Path
from unittest.mock import MagicMock

import docker
import pytest

from patchpilot.benchmarks import swebench
from patchpilot.sandbox import TestStatus

ROW = {
    "instance_id": "octo__repo-1",
    "repo": "octo/repo",
    "base_commit": "abc123",
    "patch": "--- a/x.py\n+++ b/x.py\n",
    "test_patch": "--- a/test_x.py\n+++ b/test_x.py\n",
    "problem_statement": "It crashes.",
    "FAIL_TO_PASS": '["test_x.py::test_new"]',
    "PASS_TO_PASS": '["test_x.py::test_old"]',
}


def fake_spec() -> types.SimpleNamespace:
    return types.SimpleNamespace(
        instance_image_key="swebench/sweb.eval.x86_64.octo_1776_repo-1:latest",
        eval_script="#!/bin/bash\necho run\n",
        repo="octo/repo",
    )


def test_subset_is_deterministic_and_order_independent() -> None:
    ids = [f"r__r-{i}" for i in range(300)]

    first = swebench.make_subset(ids, size=50, seed=42)
    shuffled = swebench.make_subset(list(reversed(ids)), size=50, seed=42)

    assert first == shuffled
    assert len(set(first)) == 50
    assert first == sorted(first)
    assert swebench.make_subset(ids, size=50, seed=7) != first


def test_committed_subset_file_matches_the_documented_method() -> None:
    payload = json.loads(Path("configs/swebench_lite_subset_50.json").read_text())

    assert payload["seed"] == swebench.SUBSET_SEED
    assert payload["revision"] == swebench.DATASET_REVISION
    assert len(payload["instance_ids"]) == payload["size"] == 50
    assert payload["instance_ids"] == sorted(set(payload["instance_ids"]))


def test_to_instance_uses_official_eval_script_and_does_not_double_apply_test_patch() -> None:
    instance = swebench.to_instance(ROW, fake_spec())

    assert instance.benchmark == "swebench-lite"
    assert instance.image.startswith("swebench/")
    assert instance.fail_to_pass == ("test_x.py::test_new",)
    assert instance.pass_to_pass == ("test_x.py::test_old",)
    assert instance.test_patch == ""
    assert instance.setup_files == {swebench.EVAL_SCRIPT_PATH: "#!/bin/bash\necho run\n"}
    assert instance.test_command == f"bash {swebench.EVAL_SCRIPT_PATH}"
    assert instance.log_parser == "swebench"


@pytest.fixture
def fake_harness(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    parser = MagicMock(return_value={"a": "PASSED", "b": "FAILED", "c": "XFAIL", "d": "WEIRD"})
    harness = types.SimpleNamespace(
        parsers={"octo/repo": parser}, start=">>>>> Start", end=">>>>> End"
    )
    monkeypatch.setattr(swebench, "_harness", lambda: harness)
    monkeypatch.setattr(swebench, "_test_spec", lambda _id: fake_spec())
    return parser


def test_parse_eval_log_uses_only_the_section_between_markers(fake_harness: MagicMock) -> None:
    log = "pip noise\n>>>>> Start\nreal tests\n>>>>> End\ncleanup"

    statuses = swebench.parse_eval_log("octo__repo-1", log)

    assert fake_harness.call_args.args[0] == "\nreal tests\n"
    assert statuses == {"a": TestStatus.PASSED, "b": TestStatus.FAILED, "c": TestStatus.PASSED}


def test_parse_eval_log_without_markers_means_tests_never_ran(fake_harness: MagicMock) -> None:
    assert swebench.parse_eval_log("octo__repo-1", "patch failed") == {}
    fake_harness.assert_not_called()


def test_pulled_image_removes_only_images_it_pulled() -> None:
    client = MagicMock()
    client.images.get.side_effect = docker.errors.ImageNotFound("missing")

    with swebench.pulled_image("img", client=client):
        client.images.pull.assert_called_once_with("img")

    client.images.remove.assert_called_once_with("img", force=True)


def test_pull_is_retried_when_the_download_breaks_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(swebench, "PULL_RETRY_DELAY_S", 0)
    client = MagicMock()
    missing = docker.errors.ImageNotFound("missing")
    # present? no -> pull, still missing -> pull again, now present
    client.images.get.side_effect = [missing, missing, None]

    with swebench.pulled_image("img", client=client):
        pass

    assert client.images.pull.call_count == 2


def test_pull_gives_up_after_the_last_attempt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(swebench, "PULL_RETRY_DELAY_S", 0)
    client = MagicMock()
    client.images.get.side_effect = docker.errors.ImageNotFound("missing")

    with pytest.raises(docker.errors.ImageNotFound), swebench.pulled_image("img", client=client):
        pass

    assert client.images.pull.call_count == swebench.PULL_ATTEMPTS


def test_pulled_image_keeps_images_that_were_already_present() -> None:
    client = MagicMock()

    with swebench.pulled_image("img", client=client):
        pass

    client.images.pull.assert_not_called()
    client.images.remove.assert_not_called()
