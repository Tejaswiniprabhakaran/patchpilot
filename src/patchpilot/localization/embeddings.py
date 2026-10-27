"""Embedding-based code retrieval (A3): a code embedding model + a FAISS index.

Documents (file skeletons or functions) and the bug report are embedded with the same
sentence-transformers model; cosine similarity (inner product of normalised vectors, FAISS
``IndexFlatIP``) ranks the documents. Heavy libraries are imported only when used, so the rest
of PatchPilot works without them.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

DEFAULT_MODEL = "flax-sentence-embeddings/st-codesearch-distilroberta-base"


class EmbeddingRetriever:
    name = "embedding"

    def __init__(self, model_name: str = DEFAULT_MODEL, model: Any = None) -> None:
        self.model_name = model_name
        self._model = model

    @property
    def model(self) -> Any:
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self.model_name, device="cpu")
        return self._model

    def embed(self, texts: Sequence[str], batch_size: int = 32) -> Any:
        return self.model.encode(
            list(texts), batch_size=batch_size, normalize_embeddings=True, convert_to_numpy=True
        ).astype("float32")

    def rank(
        self, query: str, doc_ids: Sequence[str], texts: Sequence[str]
    ) -> list[tuple[str, float]]:
        """Documents sorted by cosine similarity to ``query``, best first."""
        if not doc_ids:
            return []
        import faiss

        vectors = self.embed(texts)
        index = faiss.IndexFlatIP(vectors.shape[1])
        index.add(vectors)
        scores, order = index.search(self.embed([query]), len(doc_ids))
        return [(doc_ids[i], float(s)) for s, i in zip(scores[0], order[0], strict=True) if i >= 0]
