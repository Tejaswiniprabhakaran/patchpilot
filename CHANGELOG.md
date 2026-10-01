# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
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
- QuixBugs gold patches built from git objects so CRLF files apply on Windows checkouts.
- SWE-bench image pulls are verified and retried.

## [0.0.1] - 2026-09-30

### Added
- Project skeleton: `src/patchpilot` package, Typer CLI entry point with `patchpilot version`.
- Tooling: ruff, mypy (strict), pytest + coverage, pre-commit hooks.
- GitHub Actions CI running lint, format check, type check and tests on every push.
- `.gitignore`, `.gitattributes`, `.env.example`.
- `README.md` skeleton, `CLAUDE.md`, `PROGRESS.md`, `docs/decisions.md`.
