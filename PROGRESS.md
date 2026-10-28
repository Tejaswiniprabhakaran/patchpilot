# Progress log

Newest entry first. Each entry: what was done, what is next, open issues, results so far.

## How to pause and resume (resource rules, decisions D14)

```powershell
# pause everything PatchPilot runs (other projects are never touched)
powershell -File C:\dev\patchpilot\scripts\pause_patchpilot.ps1
# resume B0 on QuixBugs (skips finished instances; refuses to start a second copy)
cd C:\dev\patchpilot; powershell -File scripts/run_detached.ps1 -Name B0_quixbugs eval --config configs/exp_baseline.yaml --benchmark quixbugs
```

## 2026-10-28 — All software built; experiments and training still pending

**Done (PRs #20–#26, all merged into `develop`, CI green, 172 unit tests)**
- Phases 2–4 merged: agent + CLI, localization data/baselines/ranker/notebook 01, patch-generation
  data/notebook 02.
- BM25 held-out localization baseline: function Top-1 25.8%, Top-5 52.9%, MRR 0.390 (n=1,107);
  file Top-1 52.2% (`results/localization/heldout_bm25_test.json`).
- Evaluation statistics, results tables (`results/summary/`) and figures (`report/figures/`).
- Failure analysis: classifier + LLM judge + blind labelling; first taxonomy on B0's 7 failures so
  far (`results/analysis/taxonomy.md`, B0 incomplete).
- Dashboard (`patchpilot dashboard`, 127.0.0.1:8765), verified in the browser on real B0 results.
- GitHub Action / PR bot (`github_action/`), tested with fakes.
- Final README, `docs/architecture.md`, model cards, explainers for every component.
- Commit/push helper `scripts/dev/gate.sh`: pushes use the gh account because a second GitHub
  account is stored in the Windows credential manager.

**Blocked on the owner**
- Docker Desktop is down: B0 stopped at 16/40 QuixBugs; every experiment needs Docker.
- Kaggle notebooks 01 and 02 not run yet: no trained ranker or fine-tuned model on the Hub.
- Creating the public demo repository `Tejaswiniprabhakaran/patchpilot-demo` was blocked by the
  permission system; it is ready locally at `C:\dev\patchpilot-demo` (pricing library, tests,
  workflow). Needs the owner's approval or the owner to create the GitHub repo.
- Report: decide whether the university-format report is still wanted for a resume project.

**Next (once unblocked)**
- Finish B0 (QuixBugs, then 10 SWE-bench instances one image at a time), tag v0.1.0.
- Evaluate the ranker (held-out + SWE-bench), run E1; swap in the fine-tuned model, run E2/E3.
- Manual labels for 30 failures; re-run summaries, figures, taxonomy; releases.

## 2026-10-04 — Datasets built and on the Hub; Kaggle checkpoint

**Done**
- Localization dataset (`data/localization`): 6,329 / 1,020 / 1,212 instances, split by repository
  (`results/localization/dataset_stats.json`, `dataset_function_stats.json`), uploaded to
  `Tejaswiniprabhakaran19/patchpilot-localization`. Function-level scoring now ignores
  module-level labels (`function_targets`).
- Phase 4 started (`data/patchgen`, worktree `C:\dev\patchpilot-gen`): SFT data builder, notebook
  02 (Gemma 4 E4B QLoRA -> GGUF Q4_K_M), dataset card, decision D15. Dataset 3,063 / 494 / 580
  chats (`results/patchgen/dataset_stats.json`), uploaded to
  `Tejaswiniprabhakaran19/patchpilot-patchgen`.
- Cleanup: oracle cache, small test builds and SWE-bench train caches deleted (~730 MB).

**Waiting on the owner**
- Run notebook 01 on Kaggle (then notebook 02); screenshots `kaggle_fl_training.png`,
  `kaggle_fl_loss.png`.
- Docker Desktop is down: B0 is stopped at 16/40 QuixBugs instances.

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
