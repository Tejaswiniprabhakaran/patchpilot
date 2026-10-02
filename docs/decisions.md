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

## D8 — The agent sees the failing test (test-guided repair) (2026-10-01)

**Decision:** at the start of a run the instance's test patch is applied, so the agent can read and
run the failing test, and the retry loop uses its output as feedback.

**Why:** the brief describes an agent that "reads a failing test" and a GitHub bot that reacts
when tests fail on a pull request; in both, the failing test exists. Grading still uses the
official eval script (which resets test files before applying the test patch), and the agent may
not edit test files, so a fix cannot come from changing the test.

**Consequence:** SWE-bench numbers from this project are **not comparable** to the public
leaderboard, where the tests are hidden. This is stated next to every SWE-bench result.

## D9 — Experiment trajectories are committed, gzipped (2026-10-01)

**Decision:** `patchpilot eval` writes every trajectory to
`results/<experiment>/trajectories/<run_id>.json.gz`; ad-hoc `patchpilot fix` runs go to the
ignored `runs/` folder.

**Why:** the failure analysis (A5), the dashboard and the report's case studies all need the full
trajectories, and the "every number traceable to results/" rule means they must be in the repo.
Long step outputs are clipped at 20,000 characters and gzip keeps each run small.

## D10 — Gemma 4 "thinking" is switched off (2026-10-01)

**Measured:** on the first real run (`runs/gcd-c93b6284.json`, QuixBugs `gcd`, Gemma 4 E4B) the
localization call and the first repair call returned an empty answer: the model spent the whole
output budget on hidden reasoning (`finish_reason: length`). Replaying the same localization prompt
with a 512-token limit: default settings gave an empty answer after 512 tokens (1,578 characters
of reasoning); with `reasoning_effort: none` the model gave the correct JSON in 43 tokens.

**Decision:** all configs set `llm.reasoning_effort: none`. Thinking roughly multiplies output
tokens, which this CPU-bound setup cannot afford, and an answer cut off mid-thought is worthless
to the agent. Thinking on/off could be added as an extra ablation later if time allows.

**Also fixed from the same run:** the model copied the displayed line numbers into its SEARCH
blocks; the parser now strips them, and "not found" feedback shows the closest real lines.

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

## D12 — CPU-scale experiments: Gemma 4 E4B on the laptop, smaller evaluation set (2026-10-01)

**Measured** (`results/llm_speed_cpu.jsonl`, Gemma 4 E4B, Ollama, laptop CPU, 256 output tokens):
prompt processing 14.4 / 19.4 / 30.3 tokens/s and generation 5.3 / 0.5 / 0.8 tokens/s for
prompts of 1,102 / 4,412 / 8,950 tokens; 127 / 712 / 621 s per call. (25 Docker containers of
another project were running during the measurement.)

**Decision (owner's choice, replaces the "12B for reported results" part of D7):**
- Every reported experiment uses **base or fine-tuned Gemma 4 E4B** served locally by Ollama.
- QLoRA fine-tuning still runs on a free Kaggle GPU (training needs a GPU) but targets E4B; the
  adapter is merged, converted to GGUF and served locally.
- Evaluation set: **QuixBugs (40)** + **10 SWE-bench Lite instances**
  (`configs/swebench_lite_subset_10.json`: seed 42, sampled from the 49 instances of the 50-subset
  that passed the gold-patch sanity check).
- E4 (1 attempt) and E5 (1/2/3/5 attempts) are read from E3's 5-attempt trajectories instead of
  separate runs. The agent stops at its first success and runs at temperature 0 with a fixed seed,
  so "resolved within k attempts" of the 5-attempt run is what a k-attempt run would produce. This
  assumption is checked by re-running a sample with `max_attempts: 1` and comparing.

**Why:** at the measured speeds an agent call costs minutes; ~530 runs at 12B scale would take
far longer than the project allows on this laptop. The owner preferred a fully local setup over
renting or scheduling remote GPU time.

**Consequences, stated in the report:** results are for a small (4-billion-effective-parameter)
model; the SWE-bench sample is small, so per-config differences there will rarely be
statistically significant and QuixBugs carries most of the statistical power.

## D13 — Infrastructure stalls are re-run once, by a fixed rule (2026-10-02)

**Observed:** in B0, `breadth_first_search` spent 3,799 s on one model call with a 1,623-token
prompt and a 76-token answer (comparable calls take minutes), most likely because the laptop
slept; the instance's one-hour budget ran out before any repair attempt.

**Rule (decided before looking at which instances it affects):** a result row is an
infrastructure failure if the run ended with a model-server error or any single model call took
longer than 1,800 s. Such rows are moved to `results/<exp>/infra_failures.jsonl` (trajectories
kept) and the instance is run again **once**; a second infrastructure failure stays in the
results as an environment error. The rule ignores whether the bug was fixed, so it cannot favour
any configuration. The model client timeout is 1,800 s with no silent retries, and the session
keeps the laptop awake during experiments. Script: `scripts/requeue_infra_failures.py`.

## D14 — Resource limits: PatchPilot must never affect the owner's other projects (2026-10-02)

PatchPilot shares the laptop with the owner's main projects (FlagLens, NovaKart, Meridian).
Owner's rules, now binding for every session:

- C: keeps at least 20 GB free; PatchPilot uses under 10 GB in total (Docker images included).
  Sizes are checked and reported before any large download, build or image pull; temporary data
  is deleted as soon as it has been extracted; clones are shallow (`--depth 1`).
- Docker: only `patchpilot/*` and PatchPilot-pulled `swebench/*` images and `patchpilot.sandbox`
  containers are ever touched, deleted by exact name. No `docker system prune`,
  `docker image prune -a`, `docker volume prune` or `docker compose down -v`; other projects'
  containers are never stopped or changed; Docker Desktop settings are never changed.
- Reserved ports that PatchPilot must never bind: 7100-7123, 7201-7203, 9094, 9100, 9101, 9201,
  27117, 5435, 6380, 3307, 3001-3003, 4001-4023, 8081-8083, 5433, 5000, 5001, 5434.
- One heavy job at a time, at Below Normal priority; never two copies of the same evaluation.

**Consequences for the design (replaces the "keep images" update in D5):**
- SWE-bench images are pulled **one at a time**, used for every pending configuration, then
  deleted (`pulled_image(prune=True)`). About 4-5 GB is in use only while one image is active.
- The base and the fine-tuned Gemma 4 E4B (about 6 GB each in Ollama) are never installed at the
  same time: base-model experiments (B0, E1) run first, then the base model is removed before
  the fine-tuned one is loaded.

**Cleanup on 2026-10-02:** 50 `swebench/*` images and `python:3.11-slim` were deleted by name
(Docker image total 90.3 GB -> 18.0 GB), two exited sandbox containers removed, pip cache purged
(2.5 GB). Every other project's image and container was verified unchanged afterwards.
