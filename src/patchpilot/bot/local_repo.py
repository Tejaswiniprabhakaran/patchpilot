"""Turn a checked-out repository (e.g. a pull request in GitHub Actions) into a sandboxed instance.

The image is built from the repository's *tracked* files only (``git ls-files``), plus a small
generated Dockerfile. Dependencies are installed at build time, the only moment with network
access; the agent and the tests then run in the usual network-off sandbox.
"""

from __future__ import annotations

import io
import subprocess
import tarfile
from pathlib import Path
from typing import Any

from patchpilot.benchmarks import BenchmarkInstance

DOCKERFILE = """\
FROM python:{python}-slim
RUN apt-get update && apt-get install -y --no-install-recommends git patch ripgrep \\
    && rm -rf /var/lib/apt/lists/*
WORKDIR /testbed
COPY . /testbed
RUN if [ -f requirements.txt ]; then pip install --no-cache-dir -r requirements.txt; fi \\
    && if [ -f pyproject.toml ] || [ -f setup.py ]; then \\
        pip install --no-cache-dir -e . || true; fi \\
    && pip install --no-cache-dir pytest pytest-timeout
RUN git init -q && git config user.email bot@patchpilot.local && git config user.name patchpilot \\
    && git add -A && git commit -q -m "pull request under test"
ENV PYTHONDONTWRITEBYTECODE=1
"""


def tracked_files(repo: Path) -> list[str]:
    out = subprocess.run(
        ["git", "-C", str(repo), "ls-files", "-z"], capture_output=True, check=True
    ).stdout
    return [p for p in out.decode("utf-8").split("\0") if p]


def build_context(repo: Path, python: str = "3.11") -> bytes:
    """A tar build context: every tracked file plus the generated Dockerfile."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        for path in tracked_files(repo):
            full = repo / path
            if full.is_file():
                tar.add(str(full), arcname=path, recursive=False)
        data = DOCKERFILE.format(python=python).encode("utf-8")
        info = tarfile.TarInfo("Dockerfile.patchpilot")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def build_image(repo: Path, tag: str, client: Any = None, python: str = "3.11") -> str:
    import docker

    client = client or docker.from_env()
    client.images.build(
        fileobj=io.BytesIO(build_context(repo, python)),
        custom_context=True,
        dockerfile="Dockerfile.patchpilot",
        tag=tag,
        rm=True,
    )
    return tag


def make_instance(
    repo_name: str,
    sha: str,
    image: str,
    test_command: str,
    problem: str,
    protected: tuple[str, ...] = ("tests/",),
) -> BenchmarkInstance:
    return BenchmarkInstance(
        benchmark="pull-request",
        instance_id=f"{repo_name.replace('/', '__')}-{sha[:8]}",
        repo=repo_name,
        base_commit=sha,
        image=image,
        problem_statement=problem,
        test_command=test_command,
        gold_patch="",
        protected_paths=protected,
        test_timeout_s=600,
        memory="2g",
    )
