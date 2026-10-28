# Model card: PatchPilot patch generator (Gemma 4 E4B + QLoRA)

**Hub:** adapter `Tejaswiniprabhakaran19/patchpilot-gemma4-e4b-lora`, GGUF
`Tejaswiniprabhakaran19/patchpilot-gemma4-e4b-gguf` (not trained: dropped, decisions D18) ·
**Notebook:** `notebooks/02_patch_generator_lora.ipynb`

## Model

- Base: `google/gemma-4-E4B-it` (Gemma 4, Apache-2.0), instruction-tuned.
- Adapter: LoRA rank 16, alpha 32, dropout 0.05 on `q,k,v,o,gate,up,down` projections, trained on a
  4-bit NF4 quantized base (QLoRA).
- Served: adapter merged into the base model, converted to GGUF and quantized to Q4_K_M (the same
  quantization as the `gemma4:e4b` baseline in Ollama), so base and fine-tuned models are compared
  at the same size and precision.

## Intended use

Answering PatchPilot's repair prompt (bug report, failing tests, trimmed source code) with
SEARCH/REPLACE edit blocks. It is not a general chat model and was not evaluated as one.

## Training

- Data: `Tejaswiniprabhakaran19/patchpilot-patchgen` (dataset card: `docs/dataset_cards/patchgen.md`):
  3,063 training and 494 validation chats from the SWE-bench training split, single-file fixes with
  at most three hunks (decision D15).
- 1 epoch, learning rate 2e-4 (cosine, 3% warm-up), effective batch 16, max length 3,072 tokens,
  gradient checkpointing, paged 8-bit AdamW, loss on the assistant answer only, seed 42, free
  Kaggle T4 (fp16).
- Peak GPU memory and loss curves: not available (training dropped, D18).

## Evaluation

Experiments E2 (LLM-search localization) and E3/E4 (trained ranker; 3 and 1 attempts) against B0/E1
with the base model, on QuixBugs (40) and 10 SWE-bench Lite instances, compared with exact McNemar
tests: not run, because the training was dropped (decisions D18).

## Limitations and risks

- Small model (about 4 billion effective parameters) on CPU: modest fix rates expected.
- Trained on what developers changed; other correct fixes may exist.
- Proposes code changes; every patch must be reviewed by a person. PatchPilot never applies one
  without review (the GitHub bot only comments).
