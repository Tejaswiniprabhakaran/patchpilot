# Progress log

Newest entry first. Each entry: what was done, what is next, open issues, results so far.

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
