# Failure analysis, explained

**Code:** `src/patchpilot/analysis/` · **Scripts:** `classify_failures.py`, `label_failures.py`,
`failure_agreement.py` · **Half:** AI (A5)

## What it does

A resolve rate says *how often* the agent fails; research question RQ5 asks *why*. Every
unresolved run's trajectory is read and given exactly one failure category:

| Category | Meaning | How it is detected |
|---|---|---|
| Environment error | Docker or the model server crashed, or a model call stalled | error recorded, or a model call over 1,800 s |
| Invalid patch | No attempt produced an edit that applied | no edit blocks, SEARCH text not found, or the edit broke compilation and was undone |
| Wrong file | The fix went into the wrong file | the final patch edits none of the files the developers changed |
| Breaks other tests | The target tests pass but something else broke | final grading: target tests pass, previously passing tests fail |
| Wrong location | Right file, wrong function or lines | edited lines are more than 3 lines from every line the developers changed |
| Incomplete fix | Right place and some progress, but not enough | more tests pass than before, but not all |
| Out of attempts | Right place, no progress at all | every attempt used, no extra test passing |
| Overfitting | The patch special-cases the test inputs | only the LLM judge can say this |

## Rules first, a model for the hard cases

The first four categories are facts that can be read straight from the trajectory. The last three
are judgement calls, so they get a second opinion: an LLM judge sees the bug report, the
developers' fix, the agent's patch, the last test run and the rule's guess, and picks a category.
If its answer is not a valid category, the rule's label stays. This "rules + judge" design keeps
the cheap, explainable part explainable and spends model time only where it is needed.

## Comparing with the developers' fix fairly

"Where" the developers fixed the bug is computed from their patch, but **blank lines, comments
and docstrings are ignored**. QuixBugs' reference solutions have no docstrings, so every QuixBugs
gold patch also "deletes" the program's docstring; counting those lines would make an agent edit
next to a docstring look like it was in the right place. (A real example: on `kth` the bug is on
line 12, but the reference file's leading blank line made line 1 look like part of the fix until
this was handled.)

## Checking the classifier against a person

An automatic classifier is only useful if people agree with it. `label_failures.py` shows a
**seeded random sample of 30 failures** to the project owner, with everything needed to judge it,
but **not** the classifier's answer (otherwise the labels would be biased towards it).
`failure_agreement.py` then reports:

- **accuracy**: how often the two labels match;
- **Cohen's kappa**: agreement beyond what chance would produce (1 = perfect, 0 = chance level);
- a **confusion matrix** showing which categories get mixed up.

## Outputs

`results/analysis/failure_labels.jsonl` (one label per failed run), `taxonomy.csv` and
`taxonomy.md` (counts per experiment and case studies with both diffs), `manual_labels.jsonl` and
`agreement.json`.

## Alternatives we rejected

| Alternative | Why not |
|---|---|
| Labelling everything by hand | Does not scale to every experiment; the sample of 30 is used to validate the classifier instead |
| LLM judge for every run | Slow on a laptop CPU and less explainable than rules for the clear-cut cases |
| Showing the classifier's label to the human labeller | Anchors the human on the machine's answer and inflates agreement |
