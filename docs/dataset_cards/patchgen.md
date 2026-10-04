---
license: other
task_categories: [text-generation]
tags: [program-repair, code, swe-bench, sft, patchpilot]
---
# PatchPilot patch-generation dataset

Supervised fine-tuning chats for PatchPilot's patch generator (A2). Each chat is exactly the
prompt PatchPilot's agent sends to its model, followed by the developers' real fix written in the
agent's SEARCH/REPLACE edit format.

## Source

Built by `scripts/build_patchgen_data.py` (seed 42) from the **SWE-bench training split**
(`princeton-nlp/SWE-bench`, train) and the gold files' contents from `princeton-nlp/SWE-bench_oracle`.
The same seeded selection (at most 400 instances per repository) and the same repository-level
train/validation/test splits as the localization dataset are used.

## Leakage check

The training split's 35 repositories are disjoint from SWE-bench Lite's 12. `scripts/check_leakage.py`
found zero overlap with all 300 SWE-bench Lite test instances on repository, instance id,
normalised issue text and normalised gold patch (`results/leakage_check.json`).

## Construction

1. **Filter (same shape as SWE-bench Lite's own selection):** the gold patch edits exactly one
   existing non-test Python file, in at most three hunks. Larger multi-file fixes are skipped.
2. **Target:** each hunk becomes a SEARCH/REPLACE block. If the original lines are not unique in
   the file, real neighbouring lines are added until they are. Applying the blocks is checked to
   give exactly the same file as `git apply` of the gold patch; examples that fail are skipped.
3. **Prompt:** the agent's system prompt; a user turn with the issue text (max 3,000 characters),
   the tests added by the fix (max 1,500 characters) and the gold file with line numbers, whole if
   at most 150 lines, otherwise windows of 15 lines around each edit.
4. **Length:** user + assistant at most 10,000 characters (about 2,800 Gemma tokens).

## Size

TODO: not yet built. Filled in from `results/patchgen/dataset_stats.json` after the full build.

## Format

`{train,val,test}.jsonl.gz`, one chat per line:

```json
{"instance_id": "...", "repo": "owner/name", "split": "train", "files": ["pkg/mod.py"],
 "messages": [{"role": "system", "content": "..."},
              {"role": "user", "content": "## Bug report ..."},
              {"role": "assistant", "content": "Fix:\n\npkg/mod.py\n<<<<<<< SEARCH\n..."}]}
```

## Limitations

- The context shows the gold file around the edit, so the model learns to fix given good
  localization; at run time it sees the agent's localized files, which may be wrong.
- The tests are shown as the test patch, not as the failing test output the agent sees at run time.
- Only small, single-file fixes; the developers' fix is one correct answer among possibly many.

## Licence

Derived from SWE-bench (MIT). The underlying code belongs to the respective open-source projects
under their own licences.
