"""BM25 baseline for fault localization (A1).

Ranks candidate documents (files or functions) by lexical overlap with the bug report. Code
identifiers are split into their parts ("parse_HTTPHeader" -> "parse", "http", "header") so that a
bug report saying "header parsing" can match the function name.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from rank_bm25 import BM25Okapi

_WORD = re.compile(r"[A-Za-z][A-Za-z0-9]*")
_CAMEL = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|[0-9]+")
_STOP = {
    "the", "a", "an", "and", "or", "of", "to", "in", "is", "it", "for", "on", "with", "this",
    "that", "be", "as", "are", "was", "if", "not", "self", "def", "return", "import", "from",
    "none", "true", "false", "class", "py",
}  # fmt: skip


def tokenize(text: str) -> list[str]:
    """Lower-cased word pieces; identifiers are split on case changes and underscores."""
    tokens: list[str] = []
    for word in _WORD.findall(text):
        parts = [p.lower() for p in _CAMEL.findall(word)]
        whole = word.lower()
        if len(parts) > 1:
            tokens.append(whole)
        tokens.extend(parts)
    return [t for t in tokens if t not in _STOP and len(t) > 1]


class BM25Ranker:
    """Rank a fixed set of documents against a query."""

    name = "bm25"

    def __init__(self, doc_ids: Sequence[str], texts: Sequence[str]) -> None:
        if len(doc_ids) != len(texts):
            raise ValueError("doc_ids and texts must have the same length")
        self.doc_ids = list(doc_ids)
        corpus = [tokenize(text) or ["<empty>"] for text in texts]
        self._bm25 = BM25Okapi(corpus) if corpus else None

    def scores(self, query: str) -> list[float]:
        if self._bm25 is None:
            return []
        return [float(s) for s in self._bm25.get_scores(tokenize(query))]

    def rank(self, query: str) -> list[tuple[str, float]]:
        """Documents sorted best first; ties keep the input order (stable)."""
        scored = list(zip(self.doc_ids, self.scores(query), strict=True))
        return sorted(scored, key=lambda pair: -pair[1])


def document_text(path: str, content: str, max_chars: int = 20_000) -> str:
    """What BM25 sees for a file: its path (twice, paths are strong signals) and its content."""
    return f"{path} {path}\n{content[:max_chars]}"
