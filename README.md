# PatchPilot

[![CI](https://github.com/Tejaswiniprabhakaran/patchpilot/actions/workflows/ci.yml/badge.svg)](https://github.com/Tejaswiniprabhakaran/patchpilot/actions/workflows/ci.yml)

**An AI agent that fixes real bugs.** PatchPilot reads a failing test, locates the bug with a
trained fault-localization model, proposes a fix with a fine-tuned open LLM (Gemma), verifies the
fix by running the tests inside a Docker sandbox, and retries with feedback. It ships with a
rigorous evaluation of how many real bugs it fixes on SWE-bench Lite and QuixBugs, and where it
fails.

> **Status:** Phase 0 (project setup). Nothing below the "Quickstart" heading has been built yet.
> See [PROGRESS.md](PROGRESS.md) for the dated log.

## Research questions

| | Question |
|---|---|
| RQ1 | How many real bugs can an open-weight LLM agent fix on SWE-bench Lite (subset) and QuixBugs, compared with baselines? |
| RQ2 | How much does a *trained* fault-localization model improve the fix rate versus plain LLM-based code search? |
| RQ3 | How much does LoRA fine-tuning the patch-generation model help versus the base model? |
| RQ4 | How much does test-feedback retrying help, and how many attempts are worth it? |
| RQ5 | Where does the agent fail? |

## The 50/50 split

| Software half | AI half |
|---|---|
| S1 Docker sandbox | A1 Trained fault-localization ranker vs BM25 |
| S2 Agent framework and tools | A2 QLoRA fine-tuned Gemma patch generator |
| S3 CLI | A3 Embedding retrieval (FAISS) |
| S4 GitHub Action / bot | A4 Evaluation, ablations, McNemar's test |
| S5 Web dashboard | A5 Failure-analysis classifier |
| S6 Tests, CI, typing, docs | A6 Model cards, dataset cards, tracking |

## Quickstart

Requires Python 3.11 and Docker.

```bash
git clone https://github.com/Tejaswiniprabhakaran/patchpilot.git
cd patchpilot
python -m venv .venv
# Windows: .venv\Scripts\activate    Linux/macOS: source .venv/bin/activate
pip install -e ".[dev]"
patchpilot version
```

## Development

```bash
ruff check . && ruff format --check . && mypy && pytest
pre-commit install
```

## Results

TODO: not yet run. Every number that appears here will name the file under `results/` it came from.

## Architecture

TODO: diagram added with the first components (Phase 1–2). See `docs/architecture.md`.

## Limitations

TODO: written alongside the evaluation (Phase 5–6).
