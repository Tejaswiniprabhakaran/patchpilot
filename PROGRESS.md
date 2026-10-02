# Progress log

Newest entry first. Each entry: what was done, what is next, open issues, results so far.

## How to pause and resume (resource rules, decisions D14)

```powershell
# pause everything PatchPilot runs (other projects are never touched)
powershell -File C:\dev\patchpilot\scripts\pause_patchpilot.ps1
# resume B0 on QuixBugs (skips finished instances; refuses to start a second copy)
cd C:\dev\patchpilot; powershell -File scripts/run_detached.ps1 -Name B0_quixbugs eval --config configs/exp_baseline.yaml --benchmark quixbugs
```

## 2026-10-02 — Phase 2 baseline running, Phase 3 started, resource rules

**Done**
- Phase 2 (`feat/agent-loop`): LLM client, tools, agent loop, CLI, runner; first real fix
  (QuixBugs `gcd`, dev run) after fixing copied line numbers and Gemma 4 thinking (D10).
- CPU speed measured (`results/llm_speed_cpu.jsonl`); owner chose CPU scale: Gemma 4 E4B,
  QuixBugs 40 + 10 SWE-bench instances (D12).
- B0 running detached at Below Normal: 13/40 QuixBugs rows so far in `results/B0/quixbugs.jsonl`
  (code `68064c3`+; one stalled row re-queued under rule D13 and re-run).
- Phase 3 (`data/localization`, worktree `C:\dev\patchpilot-loc`): patch/unit labels, BM25,
  metrics, dataset builder, leakage check (zero overlap, `results/leakage_check.json`), embedding
  retrieval, cross-encoder, RankerLocalizer, evaluation script, Kaggle notebook 01, dataset card.
- Owner's resource rules adopted (D14): 50 `swebench/*` images deleted by name (Docker 90.3 ->
  18.0 GB), pip cache purged; other projects' images/containers verified unchanged. PatchPilot now
  uses about 7.8 GB in total.

**Paused**
- Localization dataset build (pass 1 had cached 8,785/8,867 gold sources). Resume only after B0
  finishes: `cd C:\dev\patchpilot-loc` then
  `$env:PYTHONPATH="src"; C:\dev\patchpilot\.venv\Scripts\python.exe scripts/build_localization_data.py`.

**Next**
- B0 QuixBugs -> B0 SWE-bench (one image at a time) -> Phase 2 PR, v0.1.0.
- Finish the dataset build, upload it (needs the owner's Hugging Face login), Kaggle training.

**Open issues**
- Docker Desktop stops after unclean shutdowns (stale socket files); if it is down, tell the owner.
- Docker's `docker_data.vhdx` on D: is 88 GB and does not shrink by itself (owner's decision).

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
