# Model card: PatchPilot fault-localization cross-encoder

**Hub:** `Tejaswiniprabhakaran19/patchpilot-fl-cross-encoder` (TODO: not yet trained; the Kaggle
notebook pushes it here) · **Notebook:** `notebooks/01_fault_localization.ipynb`

## Model

- Base: `microsoft/unixcoder-base` (RoBERTa architecture, 125M parameters, pre-trained on code and
  comments), with a 2-class sequence-classification head.
- Input: `[bug report (first 192 tokens)] [SEP] [candidate]`, at most 384 tokens. A candidate is a
  file skeleton (path, class and function signatures, first docstring line) or a function
  (`path::Qualified.name` and its source).
- Output: probability that the candidate must be edited to fix the bug.

## Intended use

Re-ranking a shortlist (BM25 top 50) of files and then functions, inside PatchPilot's
`RankerLocalizer`. Not intended as a stand-alone bug detector.

## Training

- Data: `Tejaswiniprabhakaran19/patchpilot-localization` (dataset card:
  `docs/dataset_cards/localization.md`), SWE-bench *training* split, 26 training repositories.
- Pairs: every positive file and function of an instance, plus 4 BM25 hard-negative files and 8
  negative functions (same-file first): 113,396 training pairs, 37.8% positive (counted by running
  the notebook's data cells locally).
- 1 epoch, learning rate 2e-5, effective batch 32, warm-up 6%, weight decay 0.01, fp16, seed 42,
  free Kaggle T4.
- Training loss curve: TODO (saved by the notebook as `loss_curve.png` and `training_log.json`).

## Evaluation

| Setting | Metric | BM25 baseline | Cross-encoder |
|---|---|---|---|
| Held-out repositories, function level (n=1,107) | Top-1 / Top-5 / MRR | 25.8% / 52.9% / 0.390 | TODO: not yet run |
| Held-out repositories, file level (n=1,212) | Top-1 / Top-5 / MRR | 52.2% / 98.1% / 0.712 | TODO: not yet run |
| SWE-bench Lite subset, whole repository | file Top-1 / Top-5 | TODO: not yet run | TODO: not yet run |

Baseline numbers: `results/localization/heldout_bm25_test.json`. Ranker numbers will be computed by
`scripts/eval_localization.py` from the pushed model, never copied from the notebook.

## Limitations and risks

- Python only; trained on issue text, while the agent also has failing-test output.
- Files are seen only through their signatures; a bug in a file whose skeleton looks unrelated is
  hard to rank.
- Trained on 26 open-source repositories; performance on very different codebases is unknown.
- Leakage: repositories, instance ids, issue texts and patches are disjoint from SWE-bench Lite
  (`results/leakage_check.json`).
