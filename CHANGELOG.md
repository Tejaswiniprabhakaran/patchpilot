# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Changed
- To finish in about 10 hours (D19): the ranker trains for 2 h, the held-out evaluation uses
  100 instances, E1 runs on the SWE-bench subset only, and the failure taxonomy is rules-only.
- Fine-tuning the patch generator (E2–E4) and the Gemini reference (G1) are dropped (D18);
  the tables and the report cover B0 and E1. `scripts/finish_when_done.ps1` commits and pushes
  the results when the pipeline ends.

### Fixed
- Experiments ran with Ollama's 4,096-token default context because its OpenAI-compatible API
  ignores a per-request `num_ctx`; models now come from `configs/ollama/gemma4-e4b-32k.Modelfile`,
  `patchpilot eval` checks the server's window first, and affected runs are re-run (D17).
- `patchpilot show` printed code such as `[i] * count` as Rich markup.
- The cross-encoder used 512-token inputs at inference while the notebook trains at 384; the
  training lengths now travel with the model (`patchpilot.json`).
- `scripts/pause_patchpilot.ps1` missed `patchpilot eval` when it runs as `python.exe`.
- The GitHub Action's model cache never saved anything (Ollama's install script runs a systemd
  service that keeps models outside the cached folder) and warned on every run. The cache step is
  removed: the download took 35 s and 85 s in two runs, and a 5.5 GB cache restore is unlikely to
  be much faster. Ollama is started by hand only where the install script could not start the
  service. Verified on the demo pull request: no cache warning, and the bot still posted a working
  patch.

### Added
- CPU training of the fault-localization ranker (`scripts/train_ranker_cpu.py`, D16) and E1
  (`configs/exp_e1_ranker.yaml`, `localizer: ranker`).
- `scripts/run_pipeline.ps1`: every remaining experiment step, unattended, one heavy job at a time,
  resumable, with disk and Docker checks.
- Localization evaluation on a seeded held-out sample and on the 10-instance SWE-bench subset.
- Retries measured on the base-model runs (B0@1, E1@1) and a per-configuration retries curve.
- Report builder (`scripts/build_report.py`): result sections generated from `results/`, DOCX via
  python-docx, PDF and table of contents via Microsoft Word. `scripts/capture_figures.py`
  captures the diagrams, dashboard, CLI and bot screenshots with headless Edge.
- GitHub bot demo on `Tejaswiniprabhakaran/patchpilot-demo#1`, recorded in `results/bot_demo/`.
- Fault-localization dataset (8,561 instances, split by repository), leakage check (zero overlap),
  BM25 baseline, embedding retrieval, cross-encoder ranker, `RankerLocalizer`, evaluation script,
  Kaggle notebook 01, dataset card. BM25 held-out baseline results.
- Patch-generation dataset (4,137 chats in the agent's SEARCH/REPLACE format), Kaggle QLoRA notebook
  02 for Gemma 4 E4B with GGUF export, dataset card.
- Evaluation statistics (Wilson intervals, exact McNemar), results tables and figures from
  `results/`.
- Failure analysis: rule classifier, LLM judge, blind manual labelling, Cohen's kappa.
- Web dashboard (`patchpilot dashboard`) with live Try-it runs.
- GitHub Action / PR bot that comments verified fixes (never pushes or merges).
- Infrastructure-stall re-run rule, detached low-priority launcher, pause script, resource rules.
- Final README, architecture document, model cards.
- Docker sandbox (S1): network disabled, CPU/memory/pid limits, capabilities dropped, no host
  mounts, timeouts, safe patch application, per-test result parsing.
- QuixBugs loader and image; SWE-bench Lite loader on the official harness; seeded 50-instance
  subset (`configs/swebench_lite_subset_50.json`).
- Gold-patch sanity check (`scripts/sanity_gold_patches.py`): QuixBugs 40/40 valid.
- OpenAI-compatible LLM client with token and latency logging.
- Agent tools (list/read/search/edit/run_tests/submit), agent loop with retries and trajectories,
  LLM-search localization baseline.
- CLI commands `patchpilot fix`, `patchpilot eval`, `patchpilot show`; experiment runner.
- Local LLM speed measurement script.

### Fixed
- Function-level localization scoring ignores module-level labels.
- Failure classifier ignores docstring/blank-line changes when locating the gold fix.
- `httpx` declared for the dashboard (CI).
- QuixBugs gold patches built from git objects so CRLF files apply on Windows checkouts.
- SWE-bench image pulls are verified and retried.

## [0.0.1] - 2026-09-30

### Added
- Project skeleton: `src/patchpilot` package, Typer CLI entry point with `patchpilot version`.
- Tooling: ruff, mypy (strict), pytest + coverage, pre-commit hooks.
- GitHub Actions CI running lint, format check, type check and tests on every push.
- `.gitignore`, `.gitattributes`, `.env.example`.
- `README.md` skeleton, `CLAUDE.md`, `PROGRESS.md`, `docs/decisions.md`.
