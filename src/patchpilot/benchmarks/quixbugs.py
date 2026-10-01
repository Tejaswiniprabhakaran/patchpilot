"""QuixBugs (Python): 40 small single-function programs, each with a one-line bug.

Used as the fast development benchmark. The buggy program, its reference fix and its tests
are read from a local clone pinned to one commit; the same commit is baked into the Docker
image the tests run in.
"""

from __future__ import annotations

import difflib
import io
import subprocess
from pathlib import Path
from typing import Any

import docker

from patchpilot.benchmarks.base import BenchmarkInstance

NAME = "quixbugs"
REPO_URL = "https://github.com/jkoppel/QuixBugs.git"
COMMIT = "4257f44b0ff1181dedaedee6a447e133219fcebf"
IMAGE = f"patchpilot/quixbugs:{COMMIT[:12]}"
DEFAULT_ROOT = Path("data/raw/QuixBugs")
# Each test gets this long; several buggy programs loop forever.
PER_TEST_TIMEOUT_S = 10

_DOCKERFILE = Path(__file__).parent / "docker" / "quixbugs.Dockerfile"


def ensure_downloaded(root: Path = DEFAULT_ROOT) -> Path:
    """Clone QuixBugs at the pinned commit if it is not there yet."""
    if not (root / "python_programs").is_dir():
        root.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "clone", "--quiet", REPO_URL, str(root)], check=True)
    head = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()
    if head != COMMIT:
        subprocess.run(["git", "-C", str(root), "checkout", "--quiet", COMMIT], check=True)
    return root


def program_names(root: Path = DEFAULT_ROOT) -> list[str]:
    """Programs that have a buggy version, a reference fix and a pytest file."""
    names = []
    for test_file in sorted((root / "python_testcases").glob("test_*.py")):
        name = test_file.stem.removeprefix("test_")
        if (root / "python_programs" / f"{name}.py").is_file() and (
            root / "correct_python_programs" / f"{name}.py"
        ).is_file():
            names.append(name)
    return names


def gold_patch(root: Path, name: str) -> str:
    """Unified diff turning the buggy program into the reference solution."""
    path = f"python_programs/{name}.py"
    buggy = _read_at_commit(root, path).splitlines(keepends=True)
    fixed = _read_at_commit(root, f"correct_python_programs/{name}.py").splitlines(keepends=True)
    return "".join(
        _with_final_newlines(difflib.unified_diff(buggy, fixed, f"a/{path}", f"b/{path}"))
    )


def _read_at_commit(root: Path, path: str) -> str:
    """Exact file bytes at the pinned commit.

    Read from git objects rather than the working tree: a checkout with ``core.autocrlf=true``
    (the Windows default) rewrites line endings, and some upstream files (e.g. ``wrap.py``)
    use CRLF. A diff built from rewritten text would not apply inside the Linux image.
    """
    blob = subprocess.run(
        ["git", "-C", str(root), "show", f"{COMMIT}:{path}"], check=True, capture_output=True
    ).stdout
    return blob.decode("utf-8")


def _with_final_newlines(lines: Any) -> Any:
    for line in lines:
        if line.endswith("\n"):
            yield line
        else:
            yield line + "\n"
            yield "\\ No newline at end of file\n"


def load_instance(name: str, root: Path = DEFAULT_ROOT) -> BenchmarkInstance:
    if name not in program_names(root):
        raise KeyError(f"unknown QuixBugs program: {name}")
    test_path = f"python_testcases/test_{name}.py"
    return BenchmarkInstance(
        benchmark=NAME,
        instance_id=name,
        repo="jkoppel/QuixBugs",
        base_commit=COMMIT,
        image=IMAGE,
        problem_statement=(
            f"The function `{name}` in `python_programs/{name}.py` contains a bug: "
            f"the tests in `{test_path}` fail. Fix the function so that all of them pass. "
            "Do not modify the tests."
        ),
        test_command=(
            f"python -m pytest {test_path} -rA -q -p no:cacheprovider "
            f"--timeout={PER_TEST_TIMEOUT_S}"
        ),
        gold_patch=gold_patch(root, name),
        protected_paths=("python_testcases/", "json_testcases/"),
        test_timeout_s=300,
        memory="1g",
    )


def load_instances(root: Path = DEFAULT_ROOT) -> list[BenchmarkInstance]:
    return [load_instance(name, root) for name in program_names(root)]


def build_image(client: Any = None, force: bool = False) -> str:
    """Build the QuixBugs sandbox image if it does not exist. Returns the image tag."""
    client = client or docker.from_env()
    if not force:
        try:
            client.images.get(IMAGE)
            return IMAGE
        except docker.errors.ImageNotFound:
            pass
    client.images.build(
        fileobj=io.BytesIO(_DOCKERFILE.read_bytes()),
        tag=IMAGE,
        buildargs={"QUIXBUGS_COMMIT": COMMIT},
        rm=True,
    )
    return IMAGE
