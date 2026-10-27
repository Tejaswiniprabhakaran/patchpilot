# The fine-tuned patch generator, explained

**Code:** `src/patchpilot/patchgen/` · **Notebook:** `notebooks/02_patch_generator_lora.ipynb` ·
**Half:** AI (A2)

## What it does

Once the agent knows where the bug is, a language model writes the fix as SEARCH/REPLACE edit
blocks. PatchPilot's baseline uses Google's Gemma 4 E4B exactly as released. The fine-tuned version
is the same model after extra training on thousands of real bug fixes, so research question RQ3
can ask: *does that training help?*

## Why fine-tune at all?

A general chat model knows Python, but it has never been drilled on this exact job: read an issue
and a failing test, look at a file, and answer with edits in one strict format. Fine-tuning shows
it the job thousands of times. Two things should improve:

1. **Format:** fewer answers the agent cannot parse (missing blocks, copied line numbers,
   SEARCH text that does not match the file), all of which waste an attempt.
2. **Fix quality:** more exposure to how real maintainers fix real bugs.

## The training data

Every training example is built to look *exactly* like what the agent sends at run time:

- the agent's own system prompt;
- the bug report, the tests the developers added with their fix, and the source file with line
  numbers, trimmed around the edit the same way the agent trims files;
- as the answer, the developers' actual fix, converted from a git diff into SEARCH/REPLACE blocks.

The conversion is checked: if a SEARCH text appears more than once in the file, real neighbouring
lines are added until it is unique, and applying the blocks must give exactly the same file as
`git apply` of the original diff. Examples that fail the check are dropped.

The data comes from the SWE-bench *training* split, whose 35 repositories never appear in the
evaluation set (leakage check: zero overlap). Only fixes shaped like SWE-bench Lite's (one file,
at most three hunks) are kept, so training matches what the model is tested on (decision D15).

## How the training works: QLoRA

Gemma 4 E4B has billions of parameters; updating all of them needs far more memory than a free
Kaggle T4 GPU (16 GB) has. QLoRA makes it fit:

- **Q (4-bit quantisation):** the original weights are stored in 4 bits instead of 16 and frozen.
  They are only read, never trained.
- **LoRA (low-rank adapters):** next to each attention and MLP weight matrix, two small matrices
  (rank 16) are added and trained. Their product is a small correction to the frozen weight.
  Only these adapters, a tiny fraction of the model, are learned.
- **Gradient checkpointing** recomputes some activations instead of storing them, saving memory.
- The loss is computed **only on the answer** (the edit blocks), not on the prompt, so the model
  learns to produce fixes rather than to repeat bug reports.

## From the notebook to the laptop

The trained adapter is merged into the base model and converted to **GGUF Q4_K_M**, the same
4-bit format as the `gemma4:e4b` model Ollama runs for the baseline. That makes the comparison fair
(same size, same quantisation, same server) and lets the laptop run it on the CPU. Because both
models take about 6 GB, the base model is removed before the fine-tuned one is installed
(resource rules, decision D14).

## Alternatives we rejected

| Alternative | Why not |
|---|---|
| Full fine-tuning | Needs several times the memory of a free T4 |
| Training on unified diffs | The agent asks for SEARCH/REPLACE; training on another format would teach the wrong output |
| Including multi-file fixes | Too long for a T4 and unlike the evaluation bugs (D15) |
| A larger model (Gemma 4 12B) | Measured CPU speed makes even E4B slow on this laptop (D12) |
| Prompt engineering only | Would not answer RQ3, which is about training |
