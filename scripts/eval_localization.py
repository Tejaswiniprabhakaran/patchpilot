"""Evaluate fault-localization methods (A1, A3). Source of every localization number reported.

Two settings:

  --setting heldout   Re-ranking on the held-out *test repositories* of the built dataset. Each
                      instance's candidates are its BM25-retrieved files plus the gold files, so
                      the gold file is always present: this measures re-ranking accuracy.
  --setting swebench  End-to-end on our SWE-bench Lite evaluation instances (sanity-valid ones of
                      the 50-subset) over the WHOLE repository at the base commit, read from the
                      instance's Docker image: BM25 over every Python file, then optional
                      re-ranking of the BM25 top 50.

Methods: bm25, embedding (BM25 top-50 re-ranked by code embeddings), cross_encoder (BM25 top-50
re-ranked by the trained ranker; needs --model).

Usage:
    python scripts/eval_localization.py --setting heldout --methods bm25 embedding
    python scripts/eval_localization.py --setting swebench --methods bm25 cross_encoder \
        --model <hf-user>/patchpilot-fl-cross-encoder
Writes results/localization/<setting>_<method>.json (metrics) and .jsonl (per-instance ranks).
"""

from __future__ import annotations

import argparse
import json
import logging
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from patchpilot.agent.localize import is_test_path
from patchpilot.localization import data as locdata
from patchpilot.localization.bm25 import BM25Ranker, document_text
from patchpilot.localization.code_units import edited_units, extract_units
from patchpilot.localization.metrics import first_hit_rank, summarise
from patchpilot.localization.patches import edited_lines

OUT = Path("results/localization")
SHORTLIST = 50
RankFn = Callable[[str, Sequence[str], Sequence[str]], list[tuple[str, float]]]


def make_reranker(method: str, model: str | None) -> RankFn | None:
    if method == "bm25":
        return None
    if method == "embedding":
        from patchpilot.localization.embeddings import EmbeddingRetriever

        return EmbeddingRetriever().rank
    if method == "cross_encoder":
        if not model:
            raise SystemExit("--model is required for cross_encoder")
        from patchpilot.localization.cross_encoder import CrossEncoderRanker

        return CrossEncoderRanker(model).rank
    raise SystemExit(f"unknown method {method}")


def bm25_order(query: str, ids: list[str], texts: list[str]) -> list[str]:
    return [doc for doc, _ in BM25Ranker(ids, texts).rank(query)]


# ---------------------------------------------------------------------- held-out split


def eval_heldout(
    method: str,
    rerank: RankFn | None,
    split: str,
    limit: int | None,
    data_dir: Path = Path("data/processed/localization"),
) -> list[dict[str, Any]]:
    rows = []
    path = data_dir / f"{split}.jsonl.gz"
    for index, ex in enumerate(locdata.read_examples(path)):
        if limit and index >= limit:
            break
        file_ids = [c.cid for c in ex.files]
        file_texts = [c.text for c in ex.files]
        unit_ids = [c.cid for c in ex.units]
        unit_texts = [c.text for c in ex.units]
        if rerank is None:
            files = bm25_order(ex.query, file_ids, file_texts)
            units = bm25_order(ex.query, unit_ids, unit_texts) if unit_ids else []
        else:
            files = [d for d, _ in rerank(ex.query, file_ids, file_texts)]
            units = [d for d, _ in rerank(ex.query, unit_ids, unit_texts)] if unit_ids else []
        rows.append(
            {
                "instance_id": ex.instance_id,
                "repo": ex.repo,
                "file_candidates": len(file_ids),
                "unit_candidates": len(unit_ids),
                "file_rank": first_hit_rank(files, ex.gold_files),
                "unit_rank": first_hit_rank(units, ex.gold_units) if ex.gold_units else None,
                "has_gold_units": bool(ex.gold_units),
            }
        )
    return rows


# ---------------------------------------------------------------------- SWE-bench, full repo


def eval_swebench(method: str, rerank: RankFn | None, limit: int | None) -> list[dict[str, Any]]:
    from patchpilot.benchmarks import swebench
    from patchpilot.localization.localizer import repo_python_files

    valid = {
        r["instance_id"]
        for r in map(json.loads, Path("results/sanity_gold_patches.jsonl").read_text().splitlines())
        if r["benchmark"] == "swebench-lite" and r["valid"]
    }
    ids = [i for i in swebench.subset_ids() if i in valid][: limit or None]
    rows = []
    for instance_id in ids:
        instance = swebench.load_instance(instance_id)
        with swebench.pulled_image(instance.image, prune=True), instance.sandbox() as box:
            box.reset()
            all_files = repo_python_files(box)
        files = {p: c for p, c in all_files.items() if not is_test_path(p)}
        edits = edited_lines(instance.gold_patch)
        gold_files = [p for p in edits if p in files]
        gold_units = [
            f"{p}::{name}"
            for p in gold_files
            for name in edited_units(extract_units(p, files[p]), edits[p].lines)
        ]
        ranked = bm25_order(
            instance.problem_statement, list(files), [document_text(p, c) for p, c in files.items()]
        )
        if rerank is not None:
            shortlist = ranked[:SHORTLIST]
            reranked = [
                d
                for d, _ in rerank(
                    instance.problem_statement,
                    shortlist,
                    [locdata.file_skeleton(p, files[p]) for p in shortlist],
                )
            ]
            ranked = reranked + ranked[SHORTLIST:]
        # Function level: the functions of the top-3 files, ranked by the same method.
        units = [u for p in ranked[:3] for u in extract_units(p, files[p])]
        unit_ids = [u.unit_id for u in units]
        unit_texts = [locdata.unit_text(u.path, u.name, u.source) for u in units]
        if not units:
            unit_order: list[str] = []
        elif rerank is None:
            unit_order = bm25_order(instance.problem_statement, unit_ids, unit_texts)
        else:
            unit_order = [d for d, _ in rerank(instance.problem_statement, unit_ids, unit_texts)]
        rows.append(
            {
                "instance_id": instance_id,
                "repo": instance.repo,
                "repo_python_files": len(files),
                "gold_files": gold_files,
                "file_rank": first_hit_rank(ranked, gold_files),
                "unit_rank": first_hit_rank(unit_order, gold_units) if gold_units else None,
                "has_gold_units": bool(gold_units),
            }
        )
        print(f"{instance_id}: file rank {rows[-1]['file_rank']}", flush=True)
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--setting", choices=["heldout", "swebench"], required=True)
    parser.add_argument("--methods", nargs="+", default=["bm25"])
    parser.add_argument("--model", help="cross-encoder folder or Hugging Face model id")
    parser.add_argument("--split", default="test", help="held-out split to use (test or val)")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--data-dir", type=Path, default=Path("data/processed/localization"))
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()
    logging.disable(logging.WARNING)
    out = args.out
    out.mkdir(parents=True, exist_ok=True)

    for method in args.methods:
        rerank = make_reranker(method, args.model)
        if args.setting == "heldout":
            rows = eval_heldout(method, rerank, args.split, args.limit, args.data_dir)
        else:
            rows = eval_swebench(method, rerank, args.limit)
        unit_rows = [r for r in rows if r["has_gold_units"]]
        metrics = {
            "setting": args.setting,
            "split": args.split if args.setting == "heldout" else "swebench-lite subset (valid)",
            "method": method,
            "model": args.model if method == "cross_encoder" else None,
            "file_level": summarise([r["file_rank"] for r in rows]),
            "function_level": summarise([r["unit_rank"] for r in unit_rows]),
        }
        stem = f"{args.setting}_{method}" + (f"_{args.split}" if args.setting == "heldout" else "")
        (out / f"{stem}.jsonl").write_text(
            "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8", newline="\n"
        )
        (out / f"{stem}.json").write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
