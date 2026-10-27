---
license: other
task_categories: [text-classification]
tags: [fault-localization, code, swe-bench, patchpilot]
---
# PatchPilot fault-localization dataset

Training data for PatchPilot's fault-localization cross-encoder (A1): pairs of a **bug report**
and a **code candidate** (a file or a function), labelled 1 if the developers' fix edits that
candidate.

## Source

Built by `scripts/build_localization_data.py` (seed 42) from three public datasets by Princeton NLP:

| Dataset | Used for |
|---|---|
| `princeton-nlp/SWE-bench` (train split) | issue text, gold patch, repository |
| `princeton-nlp/SWE-bench_oracle` (train) | contents of the files the gold patch edits |
| `princeton-nlp/SWE-bench_bm25_27K` (train) | contents of BM25-retrieved files (hard negatives) |

Only the SWE-bench **training** split is used. Its 35 repositories are disjoint from the 12
repositories of SWE-bench Lite (our evaluation set).

## Leakage check

`scripts/check_leakage.py` compares every selected training instance, and the whole training
split, with all 300 SWE-bench Lite test instances on repository, instance id, normalised issue
text and normalised gold patch. Result (`results/leakage_check.json`): **zero overlap on all four
keys**.

## Construction

1. **Selection:** at most 400 instances per repository (seeded), so `pandas` (5,049 instances) does
   not dominate.
2. **Labels:** the gold patch is parsed into edited files and original-file line numbers
   (insertions are attributed to the preceding line); Python's `ast` maps those lines to the
   innermost enclosing function. Test files, non-Python files and newly created files are not
   localization targets.
3. **Candidates:** gold files + BM25-retrieved Python files. Functions: every function of a gold
   file (positives and in-file hard negatives) and up to 40 functions of each other file.
4. **Text views:** a file is its path plus class/function signatures and one-line docstrings
   (max 3,000 characters); a function is `path::Qualified.name` plus its source (max 2,000
   characters); the query is the issue text (max 4,000 characters).
5. **Splits:** by repository (whole repositories go to train, validation or test), so validation
   and test measure generalisation to unseen codebases.

## Size

From `results/localization/dataset_stats.json` and `results/localization/dataset_function_stats.json`:

| Split | Repositories | Instances | File candidates (positive) | Function candidates (positive functions) | Instances with a gold function |
|---|---|---|---|---|---|
| train | 26 | 6,329 | 44,665 (15,931) | 824,343 (26,794) | 5,378 |
| val | 5 | 1,020 | 6,382 (3,188) | 125,239 (4,116) | 888 |
| test | 4 | 1,212 | 7,296 (3,263) | 208,766 (6,066) | 1,107 |

- Validation repositories: huggingface/transformers, open-mmlab/mmdetection, pypa/pip, scipy/scipy,
  tiangolo/fastapi. Test repositories: apache/airflow, conda/conda, explosion/spaCy,
  mesonbuild/meson. No repository appears in more than one split.
- Of the 8,867 selected instances, 101 do not appear in `SWE-bench_oracle`'s train split and 205
  edit no existing non-test Python file; the remaining 8,561 were built.
- Median candidates per instance: 5-6 files and 91-112 functions.
- **Module-level edits:** an edited line outside any function (imports, class attributes, new
  top-level code) is labelled `path::<module>` (10,268 / 2,073 / 2,000 such labels in
  train / val / test). No candidate is ever a whole module, so these labels are excluded from
  function-level scoring (`function_targets()`); 951 / 132 / 105 instances only edit module-level
  code and are therefore scored at file level only. The `positive_functions` field of
  `dataset_stats.json` counts these labels too.

## Format

`{train,val,test}.jsonl.gz`, one JSON object per instance:

```json
{"instance_id": "...", "repo": "owner/name", "split": "train", "query": "issue text",
 "gold_files": ["pkg/mod.py"], "gold_units": ["pkg/mod.py::Class.method"],
 "files": [{"cid": "pkg/mod.py", "text": "skeleton", "label": 1}, ...],
 "units": [{"cid": "pkg/mod.py::Class.method", "text": "source", "label": 1}, ...]}
```

## Limitations

- Python only; issue text only (no failing-test output, unlike PatchPilot's agent at run time).
- BM25 candidates come from the SWE-bench 27K-token retrieval, so a file's negatives are capped by
  what fit in that context.
- Labels mark what the developers edited; a different correct fix could edit other places.

## Licence

Derived from SWE-bench (MIT). The underlying code belongs to the respective open-source projects
under their own licences.
