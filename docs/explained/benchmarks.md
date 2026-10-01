# The benchmarks, explained

**Code:** `src/patchpilot/benchmarks/` · **Half:** SOFTWARE (S1), feeding AI (A4)

## What it does

A benchmark is a list of real bugs, each with tests that decide whether a fix is correct. Every
bug becomes one `BenchmarkInstance`, which records:

- which Docker image holds the buggy code, and at which commit;
- the problem description given to the agent;
- the command that runs the deciding tests;
- `fail_to_pass`: tests that fail now and must pass after the fix;
- `pass_to_pass`: tests that pass now and must still pass (catches fixes that break something);
- the reference ("gold") patch written by the original developers.

`evaluate_patch(instance, patch)` applies a candidate fix to a fresh checkout and runs the tests.
A fix counts as **resolved** only if every `fail_to_pass` test passes **and** every
`pass_to_pass` test still passes. A run that times out is never resolved, and a target test that
did not run at all counts as a failure.

## The two benchmarks

### QuixBugs (development benchmark)

40 small Python programs (`gcd`, `quicksort`, `levenshtein`...), each with a one-line bug and a
pytest file. Each instance takes seconds to run, so it is ideal for building and debugging the agent.

- Pinned to upstream commit `4257f44b`.
- Our Docker image **deletes the reference solutions** (`correct_python_programs/`) so the agent
  cannot cheat by reading them, then commits that state so `git diff` shows only the agent's edits.
- `pytest-timeout` gives each test 10 seconds, because several buggy programs loop forever.
- Gold patches are built from git objects, not files on disk. On Windows, git rewrites line
  endings on checkout, and some upstream files (e.g. `wrap.py`) use Windows line endings, so a
  diff built from the rewritten files would not apply inside the Linux container. (This bug was
  found by the sanity check and is covered by a unit test.)

### SWE-bench Lite (main evaluation)

300 real GitHub issues from 12 popular Python projects (Django, SymPy, scikit-learn...). These
are much harder: real codebases with thousands of files.

- Dataset pinned to revision `6ec7bb89` on the Hugging Face Hub.
- Main evaluation set: **50 instances, chosen at random with seed 42**
  (`configs/swebench_lite_subset_50.json`). All 300 can be run with `load_instances()`.
- Correctness is decided by the **official SWE-bench harness**: its per-instance eval script
  (resets test files, applies the hidden test patch, runs the project's own test command) and
  its per-project log parsers. Only the container runner is ours, so grading runs in the same
  network-off sandbox as the agent.
- The official, pre-built `swebench/sweb.eval.*` images are pulled from Docker Hub (about 4 GB each).

## The sanity check

Before trusting any result we check each instance itself: tests must **fail** on the buggy code
and **pass** with the gold patch. An instance that fails this cannot tell a good fix from a bad
one. `scripts/sanity_gold_patches.py` writes one line per instance to
`results/sanity_gold_patches.jsonl`.

## Alternatives we rejected

| Alternative | Why not |
|---|---|
| Full SWE-bench (2,294 issues) | Far too slow and too much disk for a laptop; Lite is the standard smaller set |
| Hand-picking the 50 SWE-bench instances | Would bias the results; a seeded random sample is reproducible and fair |
| Re-implementing SWE-bench grading | Results would not be comparable with published numbers |
| Defects4J (Java) | Optional stretch goal; a second language doubles the sandbox work |
