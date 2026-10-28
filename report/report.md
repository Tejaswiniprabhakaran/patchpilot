---
title: "PatchPilot: An LLM Agent that Fixes Real Bugs with Trained Fault Localization, a Fine-Tuned Patch Generator and Sandboxed Verification"
status: DRAFT — results chapters are filled in as experiments finish; every number cites its file in results/
---

<!--
FRONT MATTER (to be completed with the owner's details before building the DOCX/PDF):
title page, bonafide certificate, declaration, acknowledgement. Placeholders:
[COLLEGE NAME] · [DEPARTMENT] · [GUIDE NAME, DESIGNATION] · [TEAM MEMBERS AND REGISTER NUMBERS] · [ACADEMIC YEAR]
-->

# Abstract

Automated program repair aims to produce correct patches for real bugs with little human effort.
Recent large language model (LLM) agents can resolve some real GitHub issues, but most rely on
large proprietary models, retrieve code with ad-hoc search and are evaluated without a careful look
at why they fail. This project builds **PatchPilot**, an end-to-end repair system that combines a
*trained* fault-localization ranker, a *fine-tuned* open-weight patch generator (Google's Gemma 4
E4B, adapted with QLoRA) and *sandboxed verification*: every candidate patch is tested inside a
network-isolated Docker container, and failing attempts are retried with the test output as
feedback. The system includes a command-line tool, a web dashboard, a GitHub bot that comments
verified fixes on failing pull requests, and an evaluation harness on QuixBugs and a seeded subset
of SWE-bench Lite with paired McNemar tests and an automatic failure taxonomy. Both training
datasets are built from the SWE-bench training split with a leakage check that finds zero overlap
with the evaluation set. On 1,212 held-out instances from repositories never seen in training, a
BM25 baseline ranks the buggy function first in 25.8% of cases (Top-5: 52.9%), the bar the trained
ranker must beat. TODO: final resolve rates, the effect of the trained ranker (RQ2), of fine-tuning
(RQ3) and of retries (RQ4), and the failure taxonomy (RQ5) are reported once the experiments finish.

# Chapter 1 — Introduction

## 1.1 Background

Software defects are expensive to find and fix. Automated program repair (APR) generates patches
automatically, usually guided by tests. Early search-based tools such as GenProg evolved program
variants until the tests passed [1]; learning-based tools translated buggy lines into fixed ones
[2]; and pre-trained code models enabled repair without task-specific training [3]. Large language
models changed the field again: conversational repair with test feedback fixes many classical
benchmark bugs cheaply [4], and agents that browse a repository, edit files and run tests can
resolve a fraction of real GitHub issues in SWE-bench [5], [6], [7], [8].

## 1.2 Problem statement

Given a repository with a failing test (and, for real issues, a bug report), produce a patch to the
source code that makes the target tests pass without breaking previously passing tests — and
explain, with evidence, how often this succeeds and why it fails when it does not.

## 1.3 Motivation

Most published agents use large proprietary models and treat localization as free-form search by
the model. A student or small team cannot run them locally, and their results say little about which
component matters. PatchPilot is built to answer that question with an open model that runs on a
laptop, a localization model that is trained rather than prompted, and a fully logged, reproducible
evaluation.

## 1.4 Objectives

1. A safe execution environment that runs untrusted repository code with no network and bounded
   resources.
2. An agent with a small, auditable tool interface and test-feedback retries, recording every step.
3. A trained fault-localization ranker compared with BM25 and embedding retrieval.
4. A QLoRA-fine-tuned Gemma 4 E4B patch generator compared with the base model.
5. A rigorous evaluation with baselines, ablations and paired statistical tests, plus a failure
   taxonomy checked against manual labels.
6. Product interfaces: CLI, dashboard and a GitHub pull-request bot.

## 1.5 Scope

Python programs only; evaluation on QuixBugs (40 programs) and a seeded 10-instance subset of
SWE-bench Lite drawn from 49 sanity-checked instances. All inference runs on a laptop CPU and all
training on a free Kaggle GPU (decision D12 in `docs/decisions.md`).

## 1.6 Research questions

| | Question |
|---|---|
| RQ1 | How many real bugs can an open-weight LLM agent fix on QuixBugs and the SWE-bench Lite subset? |
| RQ2 | How much does a trained fault-localization model improve the fix rate over LLM-based search? |
| RQ3 | How much does LoRA fine-tuning the patch generator help over the base model? |
| RQ4 | How much does test-feedback retrying help, and how many attempts are worth it? |
| RQ5 | Where does the agent fail? |

# Chapter 2 — Literature Survey

## 2.1 Automated program repair

GenProg uses genetic programming over the program's own statements, with the test suite as the
fitness function [1]. SequenceR frames repair as sequence-to-sequence translation of the buggy line,
trained on commits [2]. AlphaRepair showed that a pre-trained code model (CodeBERT) can repair bugs
"zero-shot" by filling in a masked buggy line, without training on historical fixes [3].
ChatRepair turned repair into a conversation with ChatGPT, feeding failing-test information back to
the model after each wrong patch [4] — the same feedback idea PatchPilot uses.

## 2.2 LLM coding agents and SWE-bench

SWE-bench collects 2,294 real issues from 12 Python repositories, each with the tests that the
developers' fix made pass [5]. SWE-agent designs an agent-computer interface (file viewer, search,
editor) that lets a language model act in a repository [6]. AutoCodeRover searches the program's
structure (classes and methods) and can use spectrum-based fault localization when tests exist [7].
Agentless argues that a fixed pipeline — localize, repair, validate — can match more complex agents
at lower cost [8]; PatchPilot's agent is a pipeline of the same kind, with a trained localizer.

## 2.3 Fault localization

Spectrum-based fault localization ranks program elements by how often they are executed by failing
versus passing tests [11]. DeepFL combines suspiciousness, fault-proneness and textual-similarity
features in a deep model [12]. Information-retrieval localization ranks files by textual similarity
to the bug report; BM25 [19] is the standard baseline. Pre-trained code encoders such as CodeBERT
[13] and UniXcoder [14] can be fine-tuned as *cross-encoders* that read the report and a code
candidate together, an approach that re-ranks retrieval shortlists well in text search. Dense
retrieval with vector indexes such as FAISS [17] is the usual alternative.

## 2.4 Parameter-efficient fine-tuning

LoRA trains small low-rank matrices next to frozen weights [15]; QLoRA does so on a 4-bit quantized
base model, making fine-tuning of multi-billion-parameter models possible on a single GPU [16].

## 2.5 Comparison of related work

| # | Work | Year | Repair approach | Localization | Model | Verification | Evaluation |
|---|---|---|---|---|---|---|---|
| [1] | GenProg | 2012 | genetic programming | test coverage | none | test suite | C programs |
| [2] | SequenceR | 2019 | seq2seq on buggy line | given (perfect) | trained seq2seq | tests | Defects4J |
| [3] | AlphaRepair | 2022 | cloze-style infill | given | CodeBERT (zero-shot) | tests | Defects4J, QuixBugs |
| [4] | ChatRepair | 2024 | conversational, test feedback | given | ChatGPT | tests | Defects4J, QuixBugs |
| [5] | SWE-bench | 2024 | benchmark | — | various | hidden tests | 2,294 GitHub issues |
| [6] | SWE-agent | 2024 | agent with custom interface | model-driven search | GPT-4 class | tests | SWE-bench |
| [7] | AutoCodeRover | 2024 | agent, AST-aware search | code search + SBFL | GPT-4 class | tests | SWE-bench Lite |
| [8] | Agentless | 2025 | localize-repair-validate pipeline | hierarchical, model-driven | GPT-4o class | reproduction tests | SWE-bench Lite |
| [9] | QuixBugs | 2017 | benchmark | — | — | tests | 40 programs |
| [10] | Defects4J | 2014 | benchmark | — | — | tests | Java faults |
| [11] | Spectrum-based FL | 2007 | — | coverage spectra | none | — | Siemens set |
| [12] | DeepFL | 2019 | — | learned from many features | deep network | — | Defects4J |
| [13] | CodeBERT | 2020 | — | (encoder) | pre-trained bimodal | — | code search |
| [14] | UniXcoder | 2022 | — | (encoder) | pre-trained, AST-aware | — | code search, more |
| [16] | QLoRA | 2023 | — | — | 4-bit + LoRA fine-tuning | — | instruction tuning |
| — | **PatchPilot** | 2026 | pipeline agent, test-feedback retries | **trained cross-encoder** over BM25 | **open Gemma 4 E4B + QLoRA**, on CPU | network-off Docker sandbox, official harness | QuixBugs + SWE-bench Lite subset, McNemar tests, failure taxonomy |

## 2.6 Research gap

Existing agents mostly (i) rely on large proprietary models, (ii) localize with prompting rather than
a trained, evaluated ranker, and (iii) report a single resolve rate without paired statistics or a
systematic account of failures. PatchPilot isolates the contribution of a trained localizer and of
fine-tuning with controlled ablations on an open model small enough for a laptop.

# Chapter 3 — System Requirements

## 3.1 Hardware (development machine, measured)

| Item | Value |
|---|---|
| CPU / GPU | Intel Core i5-1335U (10 cores, 12 threads) / Intel Iris Xe, no CUDA GPU |
| RAM | 15.6 GB (8 GB assigned to Docker Desktop) |
| Disk | Docker data on a separate drive; PatchPilot kept under 10 GB (decision D14) |
| Training | free Kaggle notebook GPU (NVIDIA T4, 16 GB) |

## 3.2 Software

Python 3.11; Docker Desktop (Linux containers); Ollama (Gemma 4 E4B, Q4_K_M); the official SWE-bench
harness 4.1.0; transformers, peft, trl and bitsandbytes (training); rank-bm25, FAISS and
sentence-transformers (retrieval); FastAPI, Jinja2 and Pygments (dashboard); Typer and Rich (CLI);
pytest, ruff and mypy (quality); GitHub Actions (CI and the bot).

## 3.3 Functional requirements

1. Run any benchmark instance's tests in an isolated container and report per-test results.
2. Given a failing instance, produce and verify a patch; record every step.
3. Localize faults with BM25, embeddings or the trained ranker, selectable by configuration.
4. Run experiments from a YAML file, resumably, saving raw results and trajectories.
5. Compute resolve rates, confidence intervals, paired tests, figures and a failure taxonomy.
6. Show runs, trajectories, diffs and metrics in a web dashboard; run a live demo.
7. Comment a proposed fix on a pull request whose tests fail, without pushing or merging.

## 3.4 Non-functional requirements

Security (no network for untrusted code, bounded CPU/memory/processes, no host mounts);
reproducibility (pinned dataset revisions, seeds, configs saved with results); honesty (every number
traceable to `results/`); resource frugality (one heavy job at a time, below-normal priority);
maintainability (strict typing, 172 unit tests, CI on every push).

# Chapter 4 — System Design

## 4.1 Architecture

The architecture diagram, the agent sequence diagram and the experiment data-flow diagram are in
`docs/architecture.md` (Mermaid source). The central rule: repository code only runs inside the
sandbox; every other component talks to it through a small API.

## 4.2 Modules

| Module | Half | Responsibility |
|---|---|---|
| `sandbox` | S1 | container per instance, no network, limits, safe patching, per-test parsing |
| `benchmarks` | S1 | instances, resolution rule, QuixBugs and SWE-bench Lite, sanity check |
| `tools`, `agent`, `llm` | S2 | six tools, retry loop, SEARCH/REPLACE edits, trajectories, model client |
| `cli` | S3 | `fix`, `eval`, `show`, `dashboard` |
| `bot`, `github_action` | S4 | pull-request bot |
| `dashboard` | S5 | runs, trajectories, metrics, live demo |
| tests, CI, typing | S6 | quality |
| `localization` | A1, A3 | labels, BM25, embeddings, cross-encoder, ranker localizer |
| `patchgen` + notebook 02 | A2 | fine-tuning data and QLoRA training |
| `evaluation` | A4 | runner, scoring rules, statistics, tables, figures |
| `analysis` | A5 | failure classifier, LLM judge, agreement |
| cards, `results/` | A6 | model and dataset cards, raw results |

## 4.3 The agent loop

1. Reset the checkout and apply the failing test; run the tests to capture the failure.
2. Localize: BM25 over all Python files, then the ranker (or, in the baseline, model-proposed
   keywords and code search) selects the top three files and their most suspicious functions.
3. Show the model the bug report, the failing tests and the trimmed files; parse its SEARCH/REPLACE
   blocks; apply them (each must match exactly once; edits that break compilation are undone).
4. Run the tests. If they still fail, start the next attempt from the original code with the
   previous edit and its test output as feedback, up to N attempts.
5. Submit the best candidate and grade it independently on a fresh checkout with the benchmark's
   official rule: all target tests pass and no previously passing test breaks.

## 4.4 Software / AI split

| Software half | AI half |
|---|---|
| S1 sandbox · S2 agent framework · S3 CLI · S4 GitHub bot · S5 dashboard · S6 quality | A1 trained ranker · A2 QLoRA patch model · A3 retrieval · A4 evaluation · A5 failure analysis · A6 cards and tracking |

# Chapter 5 — Implementation

Each module's design, rationale and rejected alternatives are written up in `docs/explained/`
(sandbox, benchmarks, agent, localization, patch generator, failure analysis, GitHub bot). Key points:

- **Sandbox (S1).** `DockerSandbox` starts the container with `network_mode="none"`, a memory limit
  without extra swap, a CPU and process limit, all Linux capabilities dropped and
  `no-new-privileges`. Files move through the Docker archive API (no host mounts); commands run
  under `timeout`; a patch that does not apply cleanly leaves the tree untouched.
- **Benchmarks.** QuixBugs is pinned to one upstream commit; its image deletes the reference
  solutions so the agent cannot read them. SWE-bench Lite uses the official eval scripts and log
  parsers. A gold-patch sanity check validated 40/40 QuixBugs and 49/50 SWE-bench instances
  (Chapter 7).
- **Agent (S2).** The model edits with SEARCH/REPLACE blocks; copied line numbers are stripped;
  Gemma 4's hidden "thinking" is switched off because it consumed the whole output budget in the
  first runs (decision D10). Every step is logged to a gzipped JSON trajectory.
- **Localization (A1, A3).** Labels come from parsing the gold patch into edited lines and mapping
  them to functions with Python's `ast`. Files are represented by a signature skeleton, functions by
  their source; the same views are built from the sandbox at run time.
- **Patch generator (A2).** Training chats are exactly the agent's prompt; the target is the gold
  fix rewritten as SEARCH/REPLACE blocks, verified to reproduce `git apply`.
- **Evaluation (A4).** Results are written per instance with the git commit; infrastructure stalls
  are re-run once by a fixed rule (D13); exact McNemar tests compare configurations only when both
  are complete.
- **Failure analysis (A5).** Seven rule categories plus an LLM judge for uncertain cases; gold
  regions ignore docstrings and blank lines; a blind labelling tool measures agreement.
- **Dashboard (S5) and bot (S4).** FastAPI pages over `results/`; the live page runs one fix at a
  time. The bot builds its image from a pull request's tracked files and only comments.

# Chapter 6 — Datasets and Model Training

## 6.1 Evaluation data

| Set | Size | Source | Notes |
|---|---|---|---|
| QuixBugs (Python) | 40 programs | upstream commit `4257f44b` | one-line bugs, reference solutions removed from the image |
| SWE-bench Lite subset | 50 (seed 42), 49 valid | `princeton-nlp/SWE-bench_Lite` revision `6ec7bb89` | `configs/swebench_lite_subset_50.json` |
| SWE-bench evaluation sample | 10 (seed 42) | drawn from the 49 valid | `configs/swebench_lite_subset_10.json` |

## 6.2 Training data and leakage check

Both training sets come from the SWE-bench **training** split, whose 35 repositories are disjoint
from SWE-bench Lite's 12. `scripts/check_leakage.py` compared every selected training instance (8,867)
and the whole training split with all 300 SWE-bench Lite test instances on repository, instance id,
normalised issue text and normalised gold patch: **zero overlap on every key**
(`results/leakage_check.json`).

| Dataset | Train | Validation | Test | Source file |
|---|---|---|---|---|
| Localization instances | 6,329 | 1,020 | 1,212 | `results/localization/dataset_stats.json` |
| Fix-generation chats | 3,063 | 494 | 580 | `results/patchgen/dataset_stats.json` |

Splits are by repository (validation: transformers, mmdetection, pip, scipy, fastapi; test: airflow,
conda, spaCy, meson). Dataset cards: `docs/dataset_cards/`.

## 6.3 Training setup

| | Fault-localization ranker | Patch generator |
|---|---|---|
| Base model | `microsoft/unixcoder-base` (125M) | `google/gemma-4-E4B-it` |
| Method | full fine-tuning, 2-class cross-encoder | QLoRA (4-bit NF4, LoRA r=16, α=32, dropout 0.05) |
| Data | 113,396 pairs (37.8% positive) | 3,063 chats |
| Length | 384 tokens | 3,072 tokens |
| Optimisation | lr 2e-5, batch 32, 1 epoch, fp16 | lr 2e-4 cosine, batch 16, 1 epoch, paged 8-bit AdamW |
| Hardware | Kaggle T4 | Kaggle T4 |
| Loss curves | TODO: not yet run | TODO: not yet run |

# Chapter 7 — Results and Discussion

All tables state their source; `TODO: not yet run` marks results that do not exist yet.

## 7.1 Benchmark validity (`results/sanity_summary.csv`)

| Benchmark | Instances | Fail when buggy | Pass with gold patch | Valid |
|---|---|---|---|---|
| QuixBugs | 40 | 40 | 40 | 40 |
| SWE-bench Lite subset | 50 | 50 | 49 | 49 |

`psf__requests-1963` is excluded: 50 of its tests contact an external HTTP server and the sandbox
has no network by design (D11).

## 7.2 Inference cost on the laptop (`results/llm_speed_cpu.jsonl`, Figure `llm_speed_cpu.png`)

Gemma 4 E4B processed 14.4–30.3 prompt tokens/s and generated 0.5–5.3 tokens/s for prompts of
1,102–8,950 tokens (127–712 s per call), which is why experiments run at a small scale (D12).

## 7.3 Fault localization (RQ2, part 1) (`results/localization/heldout_bm25_test.json`)

| Method | File Top-1 | File Top-5 | Function Top-1 | Function Top-3 | Function Top-5 | Function MRR |
|---|---|---|---|---|---|---|
| BM25 | 52.2% | 98.1% | 25.8% | 43.0% | 52.9% | 0.390 |
| Embedding retrieval | TODO: not yet run | | | | | |
| Trained cross-encoder | TODO: not yet run | | | | | |

Held-out re-ranking over 1,212 instances (1,107 with a gold function) from four unseen repositories.
File-level Top-5 is close to trivial (about five candidates, gold always present); the function
level (about 112 candidates) is the informative comparison. The whole-repository setting on the
SWE-bench subset: TODO: not yet run.

## 7.4 Resolve rates (RQ1, RQ3, RQ4) (`results/summary/resolve_rates.csv`)

| Config | QuixBugs | SWE-bench subset |
|---|---|---|
| B0 (LLM search, base) | in progress: 16 of 40 instances run | TODO: not yet run |
| E1 (ranker, base) | TODO: not yet run | TODO: not yet run |
| E2 (LLM search, fine-tuned) | TODO: not yet run | TODO: not yet run |
| E3 (ranker, fine-tuned, 3 attempts) | TODO: not yet run | TODO: not yet run |
| E4 (ranker, fine-tuned, 1 attempt) | TODO: not yet run | TODO: not yet run |

Paired McNemar tests (`results/summary/paired_tests.csv`) and the retries curve (E5) are computed
once the configurations they compare are complete.

## 7.5 Failure analysis (RQ5) (`results/analysis/taxonomy.md`)

On the seven failures of the incomplete B0 run so far, the rules assign: invalid patch 3 (edits that
broke indentation, for example `depth_first_search`), right file but wrong location 2 (for example
`knapsack`, where the agent rewrote an unrelated line instead of changing `weight < j` to
`weight <= j`), incomplete fix 2. These counts will change as B0 completes. Agreement with manual
labels: TODO: not yet run.

## 7.6 Answers to the research questions

RQ1–RQ5: TODO, answered from the tables above once the experiments are complete. No claim is made
before the corresponding paired test exists.

# Chapter 8 — Testing

172 unit tests (pytest) cover the sandbox (with a mocked Docker client), benchmarks, tools, the agent
loop (scripted model, in-memory sandbox), localization, patch-generation data, statistics, failure
analysis, the dashboard (FastAPI test client with a fake live runner) and the bot (faked Docker,
model and agent). Four integration tests run a real QuixBugs container and check that the network
is unreachable, runaway commands are killed and rejected patches leave the tree untouched. GitHub
Actions runs ruff, a format check, strict mypy and the unit tests on every push; every merged pull
request passed CI. Coverage: TODO (reported by `pytest --cov` in CI; to be quoted from the final run).

# Chapter 9 — Conclusion and Future Work

PatchPilot delivers a complete, tested repair system — sandbox, agent, CLI, dashboard and GitHub bot
— together with leakage-checked training data, two training pipelines sized for free hardware and an
evaluation design that isolates each component's contribution. The experimental conclusions (RQ1–RQ5)
await the remaining runs.

**Limitations.** A small model on a CPU; a small SWE-bench sample, so most per-configuration
differences there will not be statistically significant; the agent sees the failing test, so
SWE-bench numbers are not comparable with the public leaderboard (D8); Python only.

**Future work.** Running the 12B model on a GPU; reproduction-test generation so the agent can work
without a given failing test; the full 300-instance SWE-bench Lite; Java via Defects4J [10].

# References

[1] C. Le Goues, T. Nguyen, S. Forrest and W. Weimer, "GenProg: A generic method for automatic software repair," *IEEE Transactions on Software Engineering*, vol. 38, no. 1, pp. 54–72, 2012.

[2] Z. Chen, S. Kommrusch, M. Tufano, L.-N. Pouchet, D. Poshyvanyk and M. Monperrus, "SequenceR: Sequence-to-sequence learning for end-to-end program repair," *IEEE Transactions on Software Engineering*, 2019, doi: 10.1109/TSE.2019.2940179.

[3] C. S. Xia and L. Zhang, "Less training, more repairing please: Revisiting automated program repair via zero-shot learning," in *Proc. ESEC/FSE*, 2022, pp. 959–971.

[4] C. S. Xia and L. Zhang, "Keep the conversation going: Fixing 162 out of 337 bugs for $0.42 each using ChatGPT," in *Proc. ISSTA*, 2024, arXiv:2304.00385.

[5] C. E. Jimenez, J. Yang, A. Wettig, S. Yao, K. Pei, O. Press and K. Narasimhan, "SWE-bench: Can language models resolve real-world GitHub issues?," in *Proc. ICLR*, 2024, arXiv:2310.06770.

[6] J. Yang, C. E. Jimenez, A. Wettig, K. Lieret, S. Yao, K. Narasimhan and O. Press, "SWE-agent: Agent-computer interfaces enable automated software engineering," in *Advances in Neural Information Processing Systems (NeurIPS)*, 2024.

[7] Y. Zhang, H. Ruan, Z. Fan and A. Roychoudhury, "AutoCodeRover: Autonomous program improvement," in *Proc. ISSTA*, 2024, arXiv:2404.05427.

[8] C. S. Xia, Y. Deng, S. Dunn and L. Zhang, "Agentless: Demystifying LLM-based software engineering agents," in *Proc. FSE*, 2025, arXiv:2407.01489.

[9] D. Lin, J. Koppel, A. Chen and A. Solar-Lezama, "QuixBugs: A multi-lingual program repair benchmark set based on the Quixey Challenge," in *Proc. SPLASH Companion*, 2017, pp. 55–56, doi: 10.1145/3135932.3135941.

[10] R. Just, D. Jalali and M. D. Ernst, "Defects4J: A database of existing faults to enable controlled testing studies for Java programs," in *Proc. ISSTA*, 2014, pp. 437–440.

[11] R. Abreu, P. Zoeteweij and A. J. C. van Gemund, "On the accuracy of spectrum-based fault localization," in *Proc. TAIC PART*, 2007, pp. 89–98.

[12] X. Li, W. Li, Y. Zhang and L. Zhang, "DeepFL: Integrating multiple fault diagnosis dimensions for deep fault localization," in *Proc. ISSTA*, 2019.

[13] Z. Feng *et al.*, "CodeBERT: A pre-trained model for programming and natural languages," in *Findings of EMNLP*, 2020, arXiv:2002.08155.

[14] D. Guo, S. Lu, N. Duan, Y. Wang, M. Zhou and J. Yin, "UniXcoder: Unified cross-modal pre-training for code representation," in *Proc. ACL*, 2022, arXiv:2203.03850.

[15] E. J. Hu *et al.*, "LoRA: Low-rank adaptation of large language models," in *Proc. ICLR*, 2022, arXiv:2106.09685.

[16] T. Dettmers, A. Pagnoni, A. Holtzman and L. Zettlemoyer, "QLoRA: Efficient finetuning of quantized LLMs," in *Advances in Neural Information Processing Systems (NeurIPS)*, 2023, arXiv:2305.14314.

[17] J. Johnson, M. Douze and H. Jégou, "Billion-scale similarity search with GPUs," *IEEE Transactions on Big Data*, vol. 7, no. 3, pp. 535–547, 2021.

[18] Hugging Face, "Welcome Gemma 4: Frontier multimodal intelligence on device," 2026. [Online]. Available: https://huggingface.co/blog/gemma4

[19] S. Robertson and H. Zaragoza, "The probabilistic relevance framework: BM25 and beyond," *Foundations and Trends in Information Retrieval*, vol. 3, no. 4, pp. 333–389, 2009.

[20] Q. McNemar, "Note on the sampling error of the difference between correlated proportions or percentages," *Psychometrika*, vol. 12, no. 2, pp. 153–157, 1947.

[21] J. Cohen, "A coefficient of agreement for nominal scales," *Educational and Psychological Measurement*, vol. 20, no. 1, pp. 37–46, 1960.

# Appendix

- **A. Sample trajectory:** `patchpilot show <run_id>` or the dashboard; raw files in
  `results/B0/trajectories/`.
- **B. Configuration files:** `configs/exp_baseline.yaml`, `configs/agent_dev.yaml`, the seeded
  subsets in `configs/`.
- **C. User manual:** the README's Quickstart, "Reproducing the experiments" and "GitHub bot".
