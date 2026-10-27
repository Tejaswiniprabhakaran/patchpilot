"""The trained fault-localization ranker (A1): a fine-tuned code encoder used as a cross-encoder.

The bug report and one candidate (a file skeleton or a function) are fed to the encoder together
as one sequence; a classification head outputs how likely the candidate is to need editing.
Reading both texts jointly lets attention compare them token by token, which is why cross-encoders
re-rank better than embedding similarity, at the cost of one forward pass per candidate (so it
only re-ranks a shortlist).

Trained in ``notebooks/01_fault_localization.ipynb``; loaded here from a local folder or the
Hugging Face Hub for CPU inference.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

MAX_LENGTH = 512
QUERY_TOKENS = 192  # the rest of the 512 tokens go to the candidate


class CrossEncoderRanker:
    name = "cross_encoder"

    def __init__(self, model_id: str, batch_size: int = 16, scorer: Any = None) -> None:
        self.model_id = model_id
        self.batch_size = batch_size
        self._scorer = scorer  # tests inject a function (query, texts) -> scores
        self._model: Any = None
        self._tokenizer: Any = None

    def _load(self) -> None:
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        self._tokenizer = AutoTokenizer.from_pretrained(self.model_id)
        self._model = AutoModelForSequenceClassification.from_pretrained(self.model_id)
        self._model.eval()

    def scores(self, query: str, texts: Sequence[str]) -> list[float]:
        if self._scorer is not None:
            return list(self._scorer(query, list(texts)))
        if self._model is None:
            self._load()
        import torch

        query_ids = self._tokenizer(query, add_special_tokens=False)["input_ids"][:QUERY_TOKENS]
        short_query = self._tokenizer.decode(query_ids)
        out: list[float] = []
        for start in range(0, len(texts), self.batch_size):
            batch = list(texts[start : start + self.batch_size])
            encoded = self._tokenizer(
                [short_query] * len(batch),
                batch,
                truncation="only_second",
                max_length=MAX_LENGTH,
                padding=True,
                return_tensors="pt",
            )
            with torch.no_grad():
                logits = self._model(**encoded).logits
            # One logit -> use it; two logits -> probability of the "buggy" class.
            if logits.shape[-1] == 1:
                out += logits[:, 0].tolist()
            else:
                out += torch.softmax(logits, dim=-1)[:, 1].tolist()
        return out

    def rank(
        self, query: str, doc_ids: Sequence[str], texts: Sequence[str]
    ) -> list[tuple[str, float]]:
        scored = list(zip(doc_ids, self.scores(query, texts), strict=True))
        return sorted(scored, key=lambda pair: -pair[1])
