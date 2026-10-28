"""Train the fault-localization cross-encoder on the CPU (A1, decisions D16).

The recipe of notebooks/01_fault_localization.ipynb (same base model, pair sampling and 2-class
loss) at a scale a laptop CPU can finish: shorter sequences, a seeded random sample of training
instances and a time budget. A few probe steps measure the speed first; the run then trains for as
many steps as fit in the budget (at most one epoch over the sampled pairs), so the amount of data
is fixed before training starts and recorded in the log. The sequence lengths are saved next to
the model (patchpilot.json), so inference uses exactly what training used.

Usage:
    python scripts/train_ranker_cpu.py --budget-hours 4
    python scripts/train_ranker_cpu.py --max-steps 600    # repeat a logged run exactly
Writes data/models/fl-cross-encoder/ (git-ignored) and results/training/fault_localization_log.json.
"""

from __future__ import annotations

import argparse
import gzip
import json
import random
import time
from pathlib import Path
from typing import Any

from patchpilot.localization.data import LocExample, read_examples

BASE_MODEL = "microsoft/unixcoder-base"
LOG = Path("results/training/fault_localization_log.json")
PROBE_STEPS = 3
STEP_OVERHEAD = 1.1  # optimizer step and tokenization, which the probe does not time


def sample_examples(path: Path, k: int, rng: random.Random) -> list[LocExample]:
    """A seeded random sample of ``k`` examples; only the sample is held in memory."""
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        total = sum(1 for _ in handle)
    chosen = set(rng.sample(range(total), min(k, total)))
    return [ex for index, ex in enumerate(read_examples(path)) if index in chosen]


def make_pairs(
    examples: list[LocExample], rng: random.Random, neg_files: int, neg_units: int
) -> list[tuple[str, str, int]]:
    """All positives plus BM25 hard-negative files and same-file-first negative functions."""
    pairs: list[tuple[str, str, int]] = []
    for ex in examples:
        pos_f = [c for c in ex.files if c.label]
        neg_f = [c for c in ex.files if not c.label]
        pos_u = [c for c in ex.units if c.label]
        gold_paths = set(ex.gold_files)
        same_file = [c for c in ex.units if not c.label and c.cid.split("::")[0] in gold_paths]
        other = [c for c in ex.units if not c.label and c.cid.split("::")[0] not in gold_paths]
        neg_u = rng.sample(same_file, min(neg_units, len(same_file)))
        neg_u += rng.sample(other, min(neg_units - len(neg_u), len(other)))
        for c in pos_f + rng.sample(neg_f, min(neg_files, len(neg_f))) + pos_u + neg_u:
            pairs.append((ex.query, c.text, c.label))
    rng.shuffle(pairs)
    return pairs


def seconds_per_step(model: Any, collator: Any, dataset: Any, batch: int) -> float:
    """Average forward + backward time of a training batch; the weights are not changed."""
    model.train()
    times = []
    for step in range(PROBE_STEPS + 1):
        inputs = collator([dataset[i] for i in range(step * batch, (step + 1) * batch)])
        started = time.monotonic()
        model(**inputs).loss.backward()
        times.append(time.monotonic() - started)
    model.zero_grad(set_to_none=True)
    return sum(times[1:]) / PROBE_STEPS  # the first step includes one-off warm-up


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data", type=Path, default=Path("data/processed/localization/train.jsonl.gz")
    )
    parser.add_argument("--out", type=Path, default=Path("data/models/fl-cross-encoder"))
    parser.add_argument("--log", type=Path, default=LOG)
    parser.add_argument(
        "--base-model", default=BASE_MODEL, help="another model only for smoke tests"
    )
    parser.add_argument("--instances", type=int, default=2000, help="training instances sampled")
    parser.add_argument("--budget-hours", type=float, default=4.0)
    parser.add_argument("--max-steps", type=int, default=0, help="fixed step count (no probe)")
    parser.add_argument("--max-len", type=int, default=256)
    parser.add_argument("--query-tokens", type=int, default=128)
    parser.add_argument("--neg-files", type=int, default=4)
    parser.add_argument("--neg-units", type=int, default=8)
    parser.add_argument("--batch", type=int, default=16)
    parser.add_argument("--lr", type=float, default=3e-5)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    import torch
    from transformers import (
        AutoModelForSequenceClassification,
        AutoTokenizer,
        DataCollatorWithPadding,
        Trainer,
        TrainingArguments,
    )

    torch.manual_seed(args.seed)
    rng = random.Random(args.seed)
    examples = sample_examples(args.data, args.instances, rng)
    pairs = make_pairs(examples, rng, args.neg_files, args.neg_units)
    print(f"{len(examples)} instances -> {len(pairs)} pairs", flush=True)

    tok = AutoTokenizer.from_pretrained(args.base_model)

    def short(query: str) -> str:
        """The query cut to --query-tokens tokens, exactly as CrossEncoderRanker cuts it."""
        return str(
            tok.decode(tok(query, add_special_tokens=False)["input_ids"][: args.query_tokens])
        )

    class PairDataset(torch.utils.data.Dataset[dict[str, Any]]):
        def __len__(self) -> int:
            return len(pairs)

        def __getitem__(self, i: int) -> dict[str, Any]:
            query, text, label = pairs[i]
            encoded = tok(short(query), text, truncation="only_second", max_length=args.max_len)
            return dict(encoded) | {"labels": label}

    dataset = PairDataset()
    collator = DataCollatorWithPadding(tok)
    model = AutoModelForSequenceClassification.from_pretrained(args.base_model, num_labels=2)

    epoch_steps = len(pairs) // args.batch
    probe_s = None
    if args.max_steps > 0:
        steps = args.max_steps
    else:
        probe_s = seconds_per_step(model, collator, dataset, args.batch)
        steps = min(epoch_steps, int(args.budget_hours * 3600 / (probe_s * STEP_OVERHEAD)))
    print(f"training {steps} steps of {args.batch} pairs (one epoch = {epoch_steps})", flush=True)

    training = TrainingArguments(
        output_dir=str(args.out.parent / "_trainer"),
        max_steps=steps,
        learning_rate=args.lr,
        per_device_train_batch_size=args.batch,
        warmup_steps=max(1, int(0.06 * steps)),
        weight_decay=0.01,
        logging_steps=10,
        disable_tqdm=True,  # plain log lines instead of a progress bar in the pipeline log
        save_strategy="no",
        report_to="none",
        seed=args.seed,
        use_cpu=True,
        dataloader_num_workers=0,
    )
    trainer = Trainer(
        model=model,
        args=training,
        train_dataset=dataset,
        processing_class=tok,
        data_collator=collator,
    )
    started = time.monotonic()
    trainer.train()
    seconds = time.monotonic() - started

    args.out.mkdir(parents=True, exist_ok=True)
    trainer.save_model(str(args.out))
    tok.save_pretrained(str(args.out))
    settings = {
        "base_model": args.base_model,
        "max_length": args.max_len,
        "query_tokens": args.query_tokens,
    }
    (args.out / "patchpilot.json").write_text(json.dumps(settings, indent=2), encoding="utf-8")
    seen = steps * args.batch
    log = {
        "recipe": "CPU, decisions D16 (notebooks/01_fault_localization.ipynb at reduced scale)",
        "config": {k: str(v) if isinstance(v, Path) else v for k, v in vars(args).items()},
        "instances_sampled": len(examples),
        "pairs_available": len(pairs),
        "pairs_seen": seen,  # a random subset of the available pairs, none of them twice
        "positive_share": round(sum(p[2] for p in pairs) / len(pairs), 4),
        "steps": steps,
        "probe_seconds_per_step": round(probe_s, 2) if probe_s else None,
        "train_seconds": round(seconds, 1),
        "torch_threads": torch.get_num_threads(),
        "log_history": trainer.state.log_history,
    }
    args.log.parent.mkdir(parents=True, exist_ok=True)
    args.log.write_text(json.dumps(log, indent=1) + "\n", encoding="utf-8", newline="\n")
    print(f"saved the model to {args.out} and the training log to {args.log}", flush=True)


if __name__ == "__main__":
    main()
