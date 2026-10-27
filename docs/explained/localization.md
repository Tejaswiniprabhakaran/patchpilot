# Fault localization, explained

**Code:** `src/patchpilot/localization/` · **Notebook:** `notebooks/01_fault_localization.ipynb` ·
**Half:** AI (A1 trained ranker, A3 retrieval)

## What it does

Before the agent can fix a bug it must know *where* the bug is. A real repository (Django has about
2,700 Python files) is far too big to show the model, so PatchPilot narrows it down:

```
all Python files ──BM25──▶ 50 files ──trained cross-encoder──▶ top 3 files ──▶ top functions
```

The agent then reads those files (trimmed around the top functions) and writes its fix.

## The three methods we compare

| Method | Idea | Cost |
|---|---|---|
| **BM25** (baseline) | Count shared words between the bug report and each file, weighting rare words more | Milliseconds; no training |
| **Embedding retrieval** (A3) | Turn the bug report and each file into vectors with a code embedding model; similar meaning → nearby vectors (FAISS index) | One encoder pass per file |
| **Cross-encoder** (A1, trained) | Feed the bug report *and* one candidate into a fine-tuned encoder together; it outputs "how likely is this the buggy place" | One pass per (report, candidate) pair, so it only re-ranks a shortlist |

The "LLM search" baseline used by B0 is different again: the chat model proposes keywords, the
agent greps for them, and the chat model picks files (see `docs/explained/agent.md`).

### Why a cross-encoder?

An embedding model encodes the bug report and the code *separately* and compares two vectors.
A cross-encoder reads them *together*, so attention can link "header parsing fails on folded
lines" directly to a function called `_parse_folded_header`. That makes it much better at ranking,
but too slow to run on every file, which is why BM25 builds the shortlist first. This
"cheap retriever + accurate re-ranker" design is standard in search engines.

### Why identifiers are split

BM25 matches whole words, but code writes `parse_HTTPHeader`. Our tokenizer splits identifiers
into `parse`, `http`, `header` (and keeps `httpheader`), so plain-English bug reports can match code.

### What the ranker sees

A 512-token encoder cannot read a whole file. So:
- a **file** is shown as its *skeleton*: the path plus every class and function signature with the
  first line of its docstring;
- a **function** is shown as `path::Class.method` plus its source code.

The agent builds exactly the same views from the sandbox at run time, so training and use match.

## Training data (and why it does not leak)

The ranker is trained on the **SWE-bench training split**: real GitHub issues from 35 Python
repositories, each with the patch that fixed it. The patch tells us which files and functions
were edited, which are the positive examples. BM25-retrieved files that were *not* edited, and the
other functions in the edited files, are the hard negatives.

The evaluation benchmark (SWE-bench Lite) comes from 12 *different* repositories.
`scripts/check_leakage.py` proves zero overlap in repositories, instance ids, issue texts and
patches (`results/leakage_check.json`). Validation and test splits are also whole repositories
the ranker never saw, so the numbers measure generalisation to new codebases.

## Training

`microsoft/unixcoder-base` (125M parameters, pre-trained on code and comments) gets a 2-class head
and is fine-tuned for one epoch on (bug report, candidate, label) pairs on a free Kaggle T4 GPU:
fp16, sequence length 384, learning rate 2e-5, effective batch 32. Each training instance
contributes all its positives, 4 negative files and 8 negative functions (same-file functions first,
because "right file, wrong function" is the hardest mistake to avoid).

## How it is evaluated

`scripts/eval_localization.py` reports Top-1/3/5 accuracy (is a gold file or function among the first
k?) and MRR (mean of 1/rank of the first gold item), in two settings:

1. **Held-out repositories:** re-ranking each instance's candidate set (the gold file is always
   in it, so this is *re-ranking* accuracy).
2. **Our SWE-bench Lite instances, whole repository:** BM25 over every Python file, then
   re-ranking of the top 50. This is the end-to-end number that matters for the agent.

## Alternatives we rejected

| Alternative | Why not |
|---|---|
| Spectrum-based fault localization (Ochiai, Tarantula) | Needs many passing and failing tests with coverage; SWE-bench instances often have one failing test |
| Asking the chat model to read the whole repository | Does not fit in context; that is exactly what the LLM-search baseline approximates |
| Training a bi-encoder only | Faster but clearly weaker at ranking; kept as the embedding baseline instead |
| Cloning all 35 training repositories | Many GB of history; the Princeton retrieval datasets already contain the needed file contents |
