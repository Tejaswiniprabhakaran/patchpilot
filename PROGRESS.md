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

**Next**
- Phase 1: Docker sandbox (S1), QuixBugs + SWE-bench Lite loaders, gold-patch sanity check.

**Open issues**
- See the machine-constraints section below.

**Results so far**
- None. No experiment has been run.

## Machine constraints (measured 2026-09-30)

| Item | Value |
|---|---|
| Free disk on C: | 25.6 GB |
| Docker Desktop memory | 8.1 GB |
| Docker CPUs | 12 |
| Python | 3.11.9 |
| uv | not installed (pip + venv used) |
| ripgrep | not installed on host |
| Ollama | 0.35.0 |
