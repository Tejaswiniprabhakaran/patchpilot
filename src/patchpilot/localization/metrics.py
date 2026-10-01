"""Ranking metrics for fault localization: Top-k accuracy and mean reciprocal rank."""

from __future__ import annotations

from collections.abc import Iterable, Sequence


def first_hit_rank(ranking: Sequence[str], gold: Iterable[str]) -> int | None:
    """1-based rank of the first gold item, or None if no gold item was ranked."""
    targets = set(gold)
    for index, item in enumerate(ranking, start=1):
        if item in targets:
            return index
    return None


def top_k_accuracy(ranks: Sequence[int | None], k: int) -> float:
    """Share of queries whose first gold item is within the top k."""
    if not ranks:
        return 0.0
    return sum(1 for r in ranks if r is not None and r <= k) / len(ranks)


def mean_reciprocal_rank(ranks: Sequence[int | None]) -> float:
    if not ranks:
        return 0.0
    return sum(1 / r for r in ranks if r is not None) / len(ranks)


def summarise(ranks: Sequence[int | None], ks: Sequence[int] = (1, 3, 5)) -> dict[str, float]:
    out: dict[str, float] = {f"top{k}": round(top_k_accuracy(ranks, k), 4) for k in ks}
    out["mrr"] = round(mean_reciprocal_rank(ranks), 4)
    out["n"] = len(ranks)
    return out
