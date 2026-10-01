# Progress log

Newest entry first. Each entry: what was done, what is next, open issues, results so far.

## 2026-10-01 — Phase 1: sandbox + benchmarks (complete)

**Done**
- `DockerSandbox` (S1): network disabled, CPU/memory/pid limits, all capabilities dropped, no host
  mounts, `timeout`-wrapped commands, git-apply + dry-run-guarded `patch` fallback, per-test
  parsing on the full output.
- QuixBugs loader + image (reference solutions deleted from the image). Gold patches are read from
  git objects because Windows autocrlf broke CRLF files such as `wrap.py`.
- SWE-bench Lite loader on the official harness (eval script + per-repo parsers), Windows shim (D6),
  verified + retried image pulls.
- Seeded 50-instance subset: `configs/swebench_lite_subset_50.json` (seed 42).
- Docker Desktop disk moved to `D:\DockerData` by the owner; images are kept for the experiments.
- 44 unit tests + 4 Docker integration tests on this branch.

**Results** (`results/sanity_gold_patches.jsonl`, `results/sanity_summary.csv`)
- QuixBugs: 40/40 valid (fail when buggy, pass with gold patch).
- SWE-bench Lite subset: 49/50 valid. `psf__requests-1963` excluded from scoring: its tests need
  the internet and the sandbox has none (D11).

**Next**
- Phase 2 (already in progress on `feat/agent`): agent, CLI, then the B0 baseline.

## 2026-09-30 — Phase 0: setup

**Done**
- Repo created at `C:\dev\patchpilot`, pushed to `Tejaswiniprabhakaran/patchpilot` (public),
  description and topics set, `main` + `develop` branches.
- Python 3.11 project (`pyproject.toml`, `src/patchpilot`), Typer CLI stub, first tests.
- ruff, mypy strict, pytest-cov, pre-commit, GitHub Actions CI.
- `.gitignore`, `.gitattributes`, `.env.example`, README skeleton, CLAUDE.md, CHANGELOG,
  `docs/decisions.md`.

- 9 milestones and 17 issues created on GitHub (one milestone per phase).
- Docker verified: `python:3.11-slim` ran with `--network none --memory 256m --cpus 1`.
- Pulled one official SWE-bench Lite image (`pallets_1776_flask-4992`, 4.23 GB) and ran it with
  the network disabled: `/testbed` checkout and the `testbed` conda env (Python 3.11.10) work.
- CI green on the phase-0 branch.

**Next**
- Phase 1: Docker sandbox (S1), QuixBugs + SWE-bench Lite loaders, gold-patch sanity check.

**Open issues**
- **Disk space:** 21.2 GB free after one SWE-bench image. Images must be pulled and removed one
  at a time (decisions.md D5). Freeing 40+ GB would make the evaluation much faster.
- Docker Desktop has 8.1 GB RAM: SWE-bench containers run sequentially.
- No licence chosen yet (D3).

**Results so far**
- None. No experiment has been run.

## Machine constraints (measured 2026-09-30)

| Item | Value |
|---|---|
| Free disk on C: | 25.6 GB before, 21.2 GB after pulling one SWE-bench image |
| Docker Desktop memory | 8.1 GB |
| Docker CPUs | 12 |
| Python | 3.11.9 |
| uv | not installed (pip + venv used) |
| ripgrep | not installed on host |
| Ollama | 0.35.0 |
