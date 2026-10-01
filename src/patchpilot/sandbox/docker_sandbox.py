"""Docker sandbox: the only place untrusted repository code is allowed to run (S1).

A sandbox is one long-lived container for one benchmark instance. It is created with

* networking disabled (``network_mode="none"``) for its whole lifetime,
* CPU, memory and process-count limits,
* all Linux capabilities dropped and privilege escalation disabled,
* no host mounts at all: files go in and out through the Docker archive API.

Every command is wrapped in ``timeout`` so a hanging test cannot block the agent.
"""

from __future__ import annotations

import contextlib
import io
import posixpath
import tarfile
import time
from collections.abc import Callable
from types import TracebackType
from typing import Any

import docker

from patchpilot.sandbox.models import ExecResult, SandboxLimits, TestRunResult, TestStatus
from patchpilot.sandbox.parsers import parse_pytest_summary

SANDBOX_LABEL = "patchpilot.sandbox"
_TIMEOUT_EXIT_CODES = {124, 137}  # `timeout` expired / SIGKILL

TestParser = Callable[[str], dict[str, TestStatus]]


class SandboxError(RuntimeError):
    """The sandbox itself failed (as opposed to the code running inside it)."""


class DockerSandbox:
    """A network-isolated, resource-limited container holding one repository checkout."""

    def __init__(
        self,
        image: str,
        workdir: str = "/testbed",
        limits: SandboxLimits | None = None,
        shell_prefix: str = "",
        client: Any = None,
    ) -> None:
        self.image = image
        self.workdir = workdir
        self.limits = limits or SandboxLimits()
        # Run before every command, e.g. activating a conda env in SWE-bench images.
        self.shell_prefix = shell_prefix
        self._client = client
        self._container: Any = None

    # ------------------------------------------------------------------ lifecycle

    def start(self) -> None:
        if self._container is not None:
            raise SandboxError("sandbox already started")
        if self._client is None:
            self._client = docker.from_env()
        self._container = self._client.containers.run(
            self.image,
            command=["sleep", "infinity"],
            detach=True,
            network_mode="none",
            mem_limit=self.limits.memory,
            memswap_limit=self.limits.memory,  # no swap on top of the memory limit
            nano_cpus=int(self.limits.cpus * 1_000_000_000),
            pids_limit=self.limits.pids,
            cap_drop=["ALL"],
            security_opt=["no-new-privileges"],
            working_dir=self.workdir,
            labels={SANDBOX_LABEL: "1"},
            entrypoint=[],
        )

    def stop(self) -> None:
        """Remove the container. Safe to call more than once."""
        container, self._container = self._container, None
        if container is None:
            return
        with contextlib.suppress(docker.errors.NotFound):
            container.remove(force=True)

    def __enter__(self) -> DockerSandbox:
        self.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.stop()

    # ------------------------------------------------------------------ commands

    def exec(self, command: str, timeout_s: int | None = None, truncate: bool = True) -> ExecResult:
        """Run a shell command in the working directory, killed after ``timeout_s`` seconds.

        Output longer than ``limits.max_output_chars`` is cut down to its head and tail unless
        ``truncate`` is false.
        """
        container = self._require_container()
        timeout = timeout_s or self.limits.timeout_s
        script = f"{self.shell_prefix}\n{command}" if self.shell_prefix else command
        started = time.monotonic()
        exit_code, raw = container.exec_run(
            ["timeout", "-s", "KILL", str(timeout), "bash", "-c", script],
            workdir=self.workdir,
        )
        duration = time.monotonic() - started
        output = (raw or b"").decode("utf-8", errors="replace")
        return ExecResult(
            exit_code=int(exit_code),
            output=_truncate(output, self.limits.max_output_chars) if truncate else output,
            duration_s=duration,
            timed_out=exit_code in _TIMEOUT_EXIT_CODES and duration >= timeout - 1,
        )

    def run_tests(
        self,
        command: str,
        timeout_s: int | None = None,
        parser: TestParser = parse_pytest_summary,
    ) -> TestRunResult:
        """Run a test command and parse its output into one status per test.

        The parser sees the full output; only the stored copy is truncated.
        """
        result = self.exec(command, timeout_s, truncate=False)
        return TestRunResult(
            statuses=parser(result.output),
            exit_code=result.exit_code,
            output=_truncate(result.output, self.limits.max_output_chars),
            duration_s=result.duration_s,
            timed_out=result.timed_out,
        )

    # ------------------------------------------------------------------ files

    def write_file(self, path: str, content: str) -> None:
        """Create or overwrite a file. Relative paths are resolved against the workdir."""
        container = self._require_container()
        full = self._resolve(path)
        data = content.encode("utf-8")
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w") as tar:
            info = tarfile.TarInfo(name=posixpath.basename(full))
            info.size = len(data)
            info.mode = 0o644
            info.mtime = int(time.time())
            tar.addfile(info, io.BytesIO(data))
        parent = posixpath.dirname(full)
        made = self.exec(f"mkdir -p {_quote(parent)}")
        if not made.ok:
            raise SandboxError(f"cannot create {parent}: {made.output}")
        if not container.put_archive(parent, buffer.getvalue()):
            raise SandboxError(f"cannot write {full}")

    def read_file(self, path: str) -> str:
        result = self.exec(f"cat {_quote(self._resolve(path))}")
        if not result.ok:
            raise FileNotFoundError(path)
        return result.output

    # ------------------------------------------------------------------ patches

    def apply_patch(self, diff: str) -> ExecResult:
        """Apply a unified diff to the checkout. Nothing is changed if it does not apply."""
        if not diff.strip():
            return ExecResult(exit_code=1, output="empty patch", duration_s=0.0)
        patch_path = "/tmp/patchpilot.diff"
        self.write_file(patch_path, diff if diff.endswith("\n") else diff + "\n")
        result = self.exec(f"git apply --verbose {patch_path}")
        if result.ok:
            return result
        # `git apply` is strict about context; fall back to `patch`, but only after a dry run
        # succeeds so a failed attempt never leaves a half-applied tree behind.
        fallback = self.exec(
            f"patch --batch --fuzz=5 -p1 --dry-run -i {patch_path} && "
            f"patch --batch --fuzz=5 -p1 -i {patch_path}"
        )
        if fallback.ok:
            return fallback
        return ExecResult(
            exit_code=result.exit_code,
            output=f"{result.output}\n{fallback.output}",
            duration_s=result.duration_s + fallback.duration_s,
        )

    def diff(self) -> str:
        """Unified diff of everything changed in the checkout since the base commit."""
        return self.exec("git add -A && git diff --cached --no-color HEAD").output

    def reset(self) -> None:
        """Throw away every change and return to the base commit."""
        result = self.exec("git reset -q --hard HEAD && git clean -fdq")
        if not result.ok:
            raise SandboxError(f"reset failed: {result.output}")

    # ------------------------------------------------------------------ helpers

    def _require_container(self) -> Any:
        if self._container is None:
            raise SandboxError("sandbox is not started")
        return self._container

    def _resolve(self, path: str) -> str:
        return posixpath.normpath(posixpath.join(self.workdir, path))


def cleanup_orphans(client: Any = None) -> int:
    """Remove sandbox containers left behind by a crashed run. Returns how many were removed."""
    client = client or docker.from_env()
    containers = client.containers.list(all=True, filters={"label": SANDBOX_LABEL})
    for container in containers:
        container.remove(force=True)
    return len(containers)


def _quote(value: str) -> str:
    return "'" + value.replace("'", "'\\''") + "'"


def _truncate(text: str, limit: int) -> str:
    """Keep the head and the tail: test failures are summarised at the end of the output."""
    if len(text) <= limit:
        return text
    head = limit // 4
    tail = limit - head
    omitted = len(text) - limit
    return f"{text[:head]}\n... [{omitted} characters omitted] ...\n{text[-tail:]}"
