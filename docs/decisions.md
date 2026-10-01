# Decisions

Every deviation from the prescribed stack, and every ambiguous choice, with its reason.

## D1 — pip + venv instead of uv (2026-09-30)

**Decision:** manage the environment with `python -m venv` and `pip install -e ".[dev]"`.

**Why:** `uv` is not installed on the development machine and the project brief lists pip + venv
as the accepted fallback. Using the same plain-pip install locally and in CI means a fresh clone
needs nothing beyond Python 3.11.

**Rejected:** installing uv only locally (CI and the README would then diverge from what is
actually used day to day).

## D2 — hatchling as the build backend (2026-09-30)

**Decision:** `hatchling` with the `src/` layout.

**Why:** minimal configuration, supports editable installs, no `setup.py`.

## D3 — No licence file yet (2026-09-30)

**Decision:** the repository is public but has no `LICENSE` for now, at the owner's request.
To be revisited before v1.0.0.

## D4 — Docker integration tests are excluded from CI (2026-09-30)

**Decision:** tests marked `integration` run locally only; CI runs `pytest -m "not integration"`.

**Why:** they need benchmark images and a Docker daemon with real resource limits; the unit tests
mock Docker so CI stays fast and deterministic.

## D5 — SWE-bench images are pulled one at a time and removed after use (2026-09-30)

**Measured:** the official image `swebench/sweb.eval.x86_64.pallets_1776_flask-4992` is 4.23 GB
as reported by `docker image ls`, and free space on C: fell from 25.6 GB to 21.2 GB after pulling
it. The development machine cannot hold 50 such images at once.

**Decision:** the SWE-bench runner will pull an instance image, run every pending configuration
for that instance, then remove the image (`prune_images: true` in the experiment config, on by
default on this machine). Docker Desktop is limited to 8.1 GB RAM, so SWE-bench containers run one
at a time with a 4 GB memory cap.

**Rejected:** pre-pulling the whole subset (does not fit); building images locally with the
harness (slower and uses more disk than pulling the published ones).

**Update 2026-10-01:** Docker Desktop's disk image was moved to `D:\DockerData` (331 GB free),
so disk space no longer limits how many SWE-bench images can be cached. Pruning stays available
(`prune=True` in `swebench.pulled_image`) but is no longer required.

## D6 — Stub the `resource` module to import the SWE-bench harness on Windows (2026-10-01)

**Problem:** `swebench` 4.1.0 imports the Unix-only `resource` module when the package is imported,
so `import swebench` fails on Windows.

**Decision:** `patchpilot.benchmarks.swebench._harness()` registers an empty `resource` module on
Windows before importing. We only use `make_test_spec` (eval scripts, image names) and the
per-repo log parsers, which never call `resource`. Grading still uses the official eval script and
official parsers; only the container runner is ours (the same sandbox the agent uses).

**Rejected:** running the whole harness inside WSL (a second Python environment just for grading);
re-implementing the eval scripts and parsers (would no longer be the official harness).
