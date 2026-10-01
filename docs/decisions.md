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

## D7 — Gemma 4 12B for experiments, base Gemma 4 E4B for development and the demo (2026-10-01)

**Decision (owner's choice):** Gemma 4 12B (instruction-tuned) is the main model for every reported
experiment (B0–E5), including the QLoRA fine-tune on Kaggle. Gemma 4 E4B, base and not fine-tuned,
is used only for daily development, laptop testing and the dashboard's live "Try it" page. E4B is
fine-tuned only if time is left at the end.

**Guard:** if 12B QLoRA does not fit in T4 memory even with short sequences and a small LoRA rank,
the measured peak-memory numbers are reported to the owner before the main model is changed.

**Why:** Gemma 4 is the newest Gemma generation (released 2026-04-02, Apache-2.0); 12B is the
largest dense size that fits ~16 GB at 4-bit, as the brief requires. The development laptop has no
NVIDIA GPU (Intel Iris Xe, i5-1335U, 15.6 GB RAM), so a small model is needed for local work.

**Open:** where the 12B model runs during experiments is decided after measuring local CPU speed
(`results/llm_speed_cpu.jsonl`).

## D11 — Instances whose gold patch fails in the network-off sandbox are excluded from scoring (2026-10-01)

**Measured** (`results/sanity_gold_patches.jsonl`, summary in `results/sanity_summary.csv`):
QuixBugs 40/40 valid; SWE-bench Lite subset 49/50 valid. The one invalid instance,
`psf__requests-1963`, fails even with the developers' own fix because 50 of its tests (e.g.
`test_HTTP_200_OK_GET`, `test_DIGEST_AUTH_RETURNS_COOKIE`) send real HTTP requests to an external
test server, and the sandbox has no network by design.

**Decision:** keep the network disabled (security rule) and score every experiment on the
**49 valid** SWE-bench instances. The excluded instance and the reason are reported next to every
SWE-bench result. The 50-instance subset file itself is unchanged, so the sampling stays as
documented.

**Rejected:** enabling the network for this instance (breaks the security rule for untrusted
code); replacing it with another instance (would change a seeded, documented sample after seeing
results of a check).
