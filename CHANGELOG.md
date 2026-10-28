# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
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
