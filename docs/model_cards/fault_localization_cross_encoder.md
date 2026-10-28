# Model card: PatchPilot fault-localization cross-encoder

**Model used in the results:** trained on the laptop CPU with `scripts/train_ranker_cpu.py`
(decisions D16) and saved to `data/models/fl-cross-encoder/` (git-ignored; Hub upload: TODO) ·
**Full-scale GPU recipe (not run):** `notebooks/01_fault_localization.ipynb`

## Model

- Base: `microsoft/unixcoder-base` (RoBERTa architecture, 125M parameters, pre-trained on code and
  comments), with a 2-class sequence-classification head.
- Input: `[bug report (first 128 tokens)] [SEP] [candidate]`, at most 256 tokens (the notebook
  recipe: 192 and 384). A candidate is a file skeleton (path, class and function signatures, first
  docstring line) or a function (`path::Qualified.name` and its source). The lengths are saved with
  the model (`patchpilot.json`) and used at inference.
- Output: probability that the candidate must be edited to fix the bug.

## Intended use

Re-ranking a shortlist (BM25 top 50) of files and then functions, inside PatchPilot's
`RankerLocalizer`. Not intended as a stand-alone bug detector.

## Training

- Data: `Tejaswiniprabhakaran19/patchpilot-localization` (dataset card:
  `docs/dataset_cards/localization.md`), SWE-bench *training* split, 26 training repositories.
- Pairs (same rule as the notebook): every positive file and function of an instance, plus 4 BM25
  hard-negative files and 8 negative functions (same-file first).
- CPU recipe (D16): a seeded random sample of 2,000 of the 6,329 training instances; batch 16,
  learning rate 3e-5 (linear decay, 6% warm-up), weight decay 0.01, fp32, seed 42; a 2-hour
  budget (D19), turned into a step count by three timed probe steps before training (at most one epoch).
  The number of steps, pairs seen, timings and the loss curve are in
  `results/training/fault_localization_log.json`: TODO: not yet run.
- The full set has 113,396 training pairs, 37.8% positive (counted by running the notebook's data
  cells locally); the notebook trains on all of them for 1 epoch on a T4 GPU.

## Evaluation

Computed by `scripts/eval_localization.py` from the saved model, never copied from training logs.

| Setting | Metric | BM25 | Embeddings | Cross-encoder |
|---|---|---|---|---|
| Held-out repositories, all test instances, function level (n=1,107) | Top-1 / Top-5 / MRR | 25.8% / 52.9% / 0.390 | TODO | TODO |
| Held-out repositories, all test instances, file level (n=1,212) | Top-1 / Top-5 / MRR | 52.2% / 98.1% / 0.712 | TODO | TODO |
| Held-out repositories, seeded sample of 100 test instances | file and function Top-1 / Top-5 / MRR | TODO: not yet run | TODO | TODO |
| SWE-bench Lite evaluation subset, whole repository | file Top-1 / Top-5 | TODO: not yet run | TODO | TODO |

Full-test BM25 numbers: `results/localization/heldout_bm25_test.json`. The cross-encoder needs one
forward pass per candidate (about 117 candidates per instance) on the CPU, so it is evaluated on a
seeded sample of 100 held-out instances (D19), with BM25 and embeddings on the same sample.

## Limitations and risks

- Trained at reduced scale on a CPU (a sample of the training instances, shorter sequences); the
  full-scale notebook recipe may rank better.
- Python only; trained on issue text, while the agent also has failing-test output.
- Files are seen only through their signatures; a bug in a file whose skeleton looks unrelated is
  hard to rank.
- Trained on 26 open-source repositories; performance on very different codebases is unknown.
- Leakage: repositories, instance ids, issue texts and patches are disjoint from SWE-bench Lite
  (`results/leakage_check.json`).
