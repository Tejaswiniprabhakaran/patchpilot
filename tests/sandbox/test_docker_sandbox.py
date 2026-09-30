"""Unit tests for DockerSandbox with the Docker client mocked out."""

import io
import tarfile
from typing import Any
from unittest.mock import MagicMock

import docker
import pytest

from patchpilot.sandbox import DockerSandbox, SandboxError, SandboxLimits, cleanup_orphans
from patchpilot.sandbox.docker_sandbox import SANDBOX_LABEL, _truncate


def make_sandbox(
    exec_results: list[tuple[int, bytes]] | None = None, **kwargs: Any
) -> tuple[DockerSandbox, MagicMock, MagicMock]:
    client = MagicMock()
    container = client.containers.run.return_value
    if exec_results is not None:
        container.exec_run.side_effect = exec_results
    else:
        container.exec_run.return_value = (0, b"")
    sandbox = DockerSandbox("img:latest", client=client, **kwargs)
    return sandbox, client, container


def test_start_creates_isolated_limited_container() -> None:
    limits = SandboxLimits(cpus=1.5, memory="1g", pids=64)
    sandbox, client, _ = make_sandbox(limits=limits)

    sandbox.start()

    kwargs = client.containers.run.call_args.kwargs
    assert kwargs["network_mode"] == "none"
    assert kwargs["mem_limit"] == "1g"
    assert kwargs["memswap_limit"] == "1g"
    assert kwargs["nano_cpus"] == 1_500_000_000
    assert kwargs["pids_limit"] == 64
    assert kwargs["cap_drop"] == ["ALL"]
    assert kwargs["security_opt"] == ["no-new-privileges"]
    assert kwargs["labels"] == {SANDBOX_LABEL: "1"}
    assert "volumes" not in kwargs
    assert "privileged" not in kwargs


def test_start_twice_is_an_error() -> None:
    sandbox, _, _ = make_sandbox()
    sandbox.start()

    with pytest.raises(SandboxError):
        sandbox.start()


def test_exec_before_start_is_an_error() -> None:
    sandbox, _, _ = make_sandbox()

    with pytest.raises(SandboxError):
        sandbox.exec("true")


def test_context_manager_removes_container_even_when_body_raises() -> None:
    sandbox, _, container = make_sandbox()

    with pytest.raises(ValueError), sandbox:
        raise ValueError("boom")

    container.remove.assert_called_once_with(force=True)


def test_stop_is_idempotent_and_tolerates_missing_container() -> None:
    sandbox, _, container = make_sandbox()
    sandbox.start()
    container.remove.side_effect = docker.errors.NotFound("gone")

    sandbox.stop()
    sandbox.stop()

    container.remove.assert_called_once()


def test_exec_wraps_command_in_timeout_and_shell_prefix() -> None:
    sandbox, _, container = make_sandbox(
        [(3, b"oops\n")], shell_prefix="source activate testbed", workdir="/repo"
    )
    sandbox.start()

    result = sandbox.exec("pytest -q", timeout_s=42)

    argv = container.exec_run.call_args.args[0]
    assert argv[:4] == ["timeout", "-s", "KILL", "42"]
    assert argv[4:6] == ["bash", "-c"]
    assert argv[6] == "source activate testbed\npytest -q"
    assert container.exec_run.call_args.kwargs["workdir"] == "/repo"
    assert result.exit_code == 3
    assert result.output == "oops\n"
    assert not result.ok
    assert not result.timed_out


def test_exec_reports_timeout_only_when_the_time_limit_was_reached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sandbox, _, _ = make_sandbox([(137, b""), (137, b"")])
    sandbox.start()

    clock = iter([0.0, 10.0, 100.0, 100.2])
    monkeypatch.setattr("patchpilot.sandbox.docker_sandbox.time.monotonic", lambda: next(clock))

    assert sandbox.exec("sleep 99", timeout_s=10).timed_out
    # Exit 137 after 0.2 s is an out-of-memory kill, not a timeout.
    assert not sandbox.exec("python hog.py", timeout_s=10).timed_out


def test_run_tests_parses_statuses() -> None:
    output = b"PASSED t.py::test_a\nFAILED t.py::test_b - assert 0\n"
    sandbox, _, _ = make_sandbox([(1, output)])
    sandbox.start()

    result = sandbox.run_tests("pytest -rA")

    assert result.passed == ["t.py::test_a"]
    assert result.failed == ["t.py::test_b"]
    assert not result.all_passed


def test_run_with_no_parsed_tests_is_not_a_pass() -> None:
    sandbox, _, _ = make_sandbox([(0, b"no tests ran\n")])
    sandbox.start()

    assert not sandbox.run_tests("pytest -rA").all_passed


def test_write_file_sends_tar_archive_to_parent_directory() -> None:
    sandbox, _, container = make_sandbox()
    sandbox.start()

    sandbox.write_file("pkg/mod.py", "x = 1\n")

    directory, payload = container.put_archive.call_args.args
    assert directory == "/testbed/pkg"
    with tarfile.open(fileobj=io.BytesIO(payload)) as tar:
        member = tar.getmembers()[0]
        extracted = tar.extractfile(member)
        assert member.name == "mod.py"
        assert extracted is not None
        assert extracted.read() == b"x = 1\n"


def test_write_file_raises_when_docker_rejects_archive() -> None:
    sandbox, _, container = make_sandbox()
    container.put_archive.return_value = False
    sandbox.start()

    with pytest.raises(SandboxError):
        sandbox.write_file("a.py", "")


def test_read_missing_file_raises() -> None:
    sandbox, _, _ = make_sandbox([(1, b"cat: nope: No such file")])
    sandbox.start()

    with pytest.raises(FileNotFoundError):
        sandbox.read_file("nope")


def test_apply_patch_rejects_empty_diff_without_touching_container() -> None:
    sandbox, _, container = make_sandbox()
    sandbox.start()

    result = sandbox.apply_patch("  \n")

    assert not result.ok
    container.exec_run.assert_not_called()


def test_apply_patch_falls_back_to_patch_with_dry_run_first() -> None:
    # mkdir, git apply (fails), patch (succeeds)
    sandbox, _, container = make_sandbox([(0, b""), (1, b"error: patch failed"), (0, b"ok")])
    sandbox.start()

    result = sandbox.apply_patch("--- a/x\n+++ b/x\n")

    assert result.ok
    fallback_script = container.exec_run.call_args_list[-1].args[0][6]
    assert fallback_script.index("--dry-run") < fallback_script.rindex("patch --batch")


def test_apply_patch_reports_both_errors_when_nothing_applies() -> None:
    sandbox, _, _ = make_sandbox([(0, b""), (1, b"git says no"), (1, b"patch says no")])
    sandbox.start()

    result = sandbox.apply_patch("--- a/x\n+++ b/x\n")

    assert not result.ok
    assert "git says no" in result.output
    assert "patch says no" in result.output


def test_reset_failure_raises() -> None:
    sandbox, _, _ = make_sandbox([(128, b"fatal: not a git repository")])
    sandbox.start()

    with pytest.raises(SandboxError):
        sandbox.reset()


def test_cleanup_orphans_removes_labelled_containers() -> None:
    client = MagicMock()
    leftovers = [MagicMock(), MagicMock()]
    client.containers.list.return_value = leftovers

    assert cleanup_orphans(client) == 2

    client.containers.list.assert_called_once_with(all=True, filters={"label": SANDBOX_LABEL})
    for container in leftovers:
        container.remove.assert_called_once_with(force=True)


def test_truncate_keeps_head_and_tail() -> None:
    text = "A" * 50 + "B" * 50 + "C" * 50

    short = _truncate(text, 40)

    assert short.startswith("A" * 10)
    assert short.endswith("C" * 30)
    assert "110 characters omitted" in short
    assert _truncate("tiny", 40) == "tiny"
