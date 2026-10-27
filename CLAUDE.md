# PatchPilot — context for Claude Code sessions

Final-year B.Tech AI & Data Science project. An agent that fixes real bugs: trained fault
localization + fine-tuned Gemma patch generation, verified by running tests in a Docker sandbox,
evaluated on SWE-bench Lite (50-instance seeded subset) and QuixBugs.

**Read `PROGRESS.md` first** — it says which phase is current, what is next and what is blocked.

## Hard rules

1. **Never fabricate results.** Every number in README/report/charts comes from a run whose raw
   output is under `results/`. Not run yet → write `TODO: not yet run`. Every table names its
   results file.
2. **Commit small, push immediately.** Conventional Commits, body explains what and why, plus a
   `Half: SOFTWARE (S1)` / `Half: AI (A2)` line and `Refs #N` where relevant.
3. **Before every commit:** `ruff check .`, `ruff format .`, `mypy`, `pytest`. No failing tests on
   `develop` or `main`.
4. **Never commit** secrets, datasets, model weights, Docker images.
5. **50/50 rule.** Software half (S1–S6) and AI half (A1–A6) get roughly equal depth. No thin
   wrappers on either side.
6. **Untrusted repo code runs only in Docker**: network disabled during tests, CPU/memory/time
   limits, no host mounts except a scratch directory.
7. **Ask before destructive actions**: deleting outside the repo, force-push, history rewrite,
   deleting Docker volumes.
8. Every major component gets `docs/explained/<component>.md` in plain English.
9. Deviations from the prescribed stack are recorded in `docs/decisions.md`.

## Resource rules (decisions D14) — PatchPilot is a resume project; never affect other projects

- C: free space stays >= 20 GB; PatchPilot total < 10 GB (Docker images count). Check and report
  sizes before any big download/build/pull; delete temp data once extracted; `--depth 1` clones.
- Docker: touch only `patchpilot/*`, PatchPilot-pulled `swebench/*` images and
  `patchpilot.sandbox` containers, by exact name. NEVER `docker system prune`,
  `docker image prune -a`, `docker volume prune`, `docker compose down -v`. Never stop/change
  `meridian-*`, `novakart-*`, `flaglens-*`. Never change Docker Desktop settings. If Docker is
  down (stale sockets after unclean shutdown), tell the owner instead of fixing settings.
- Never bind ports 7100-7123, 7201-7203, 9094, 9100, 9101, 9201, 27117, 5435, 6380, 3307,
  3001-3003, 4001-4023, 8081-8083, 5433, 5000, 5001, 5434.
- One heavy job at a time, Below Normal priority; check the eval is not already running.
  Long jobs run detached via `scripts/run_detached.ps1`.
- Never edit, run or commit anything in `C:\dev\meridian`, `C:\devlaglens` or the NovaKart folder.
- SWE-bench images: one at a time, deleted after use. Base and fine-tuned E4B never both in Ollama.

## Git workflow

- `main` (stable) ← `develop` (integration) ← short-lived `feat/ fix/ exp/ docs/ data/ chore/`.
- One PR per phase into `develop`; wait for CI; squash-merge; delete branch.
- Releases: v0.1.0 sandbox+agent+baseline · v0.2.0 localization · v0.3.0 fine-tuned patch model ·
  v0.4.0 evaluation+failure analysis · v0.5.0 dashboard+bot · v1.0.0 report.
- `CHANGELOG.md` updated with every PR.

## Environment (this machine)

- Windows 11, repo at `C:\dev\patchpilot`, GitHub `Tejaswiniprabhakaran/patchpilot` (public).
- Python 3.11 venv at `.venv` (pip + venv; `uv` is not installed — see decisions.md).
- Run tools as `.venv\Scripts\python.exe -m ruff|mypy|pytest`.
- Docker Desktop (Linux containers). Ollama installed for local inference.
- No NVIDIA GPU (Intel Iris Xe, i5-1335U, 15.6 GB RAM). Training notebooks in `notebooks/` run on
  Kaggle/Colab by the owner (checkpoint).
- **Experiments are CPU-scale (decisions D12):** Gemma 4 E4B (base, later QLoRA-fine-tuned and
  served as GGUF) in local Ollama; evaluation set = QuixBugs (40) + 10 SWE-bench Lite instances
  (`configs/swebench_lite_subset_10.json`). Gemma 4 thinking is off (D10).
- Docker Desktop's disk lives on `D:\DockerData`; SWE-bench images are kept, not pruned.
- Commit gate: ruff check, ruff format, mypy, then **plain `pytest`** (as CI runs it).

## Commands

```bash
pip install -e ".[dev]"
ruff check . && ruff format --check . && mypy && pytest -m "not integration"
pytest -m integration        # needs Docker running
patchpilot version
```

## Layout

`src/patchpilot/{sandbox,tools,agent,llm,localization,retrieval,benchmarks,evaluation,analysis,dashboard}`,
`cli.py`, `configs/`, `notebooks/`, `scripts/`, `tests/`, `results/`, `docs/`, `report/`,
`github_action/`.
