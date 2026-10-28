"""The trained fault-localization ranker (A1): a fine-tuned code encoder used as a cross-encoder.

The bug report and one candidate (a file skeleton or a function) are fed to the encoder together
as one sequence; a classification head outputs how likely the candidate is to need editing.
Reading both texts jointly lets attention compare them token by token, which is why cross-encoders
re-rank better than embedding similarity, at the cost of one forward pass per candidate (so it
only re-ranks a shortlist).

Trained in ``notebooks/01_fault_localization.ipynb`` (GPU) or ``scripts/train_ranker_cpu.py``
(CPU, decisions D16); loaded here from a local folder or the Hugging Face Hub for CPU inference.
The sequence lengths used in training are read from the model's ``patchpilot.json`` when it has
one, so inference cuts texts exactly as training did.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

# The notebook's lengths, used for models saved without patchpilot.json.
MAX_LENGTH = 384
QUERY_TOKENS = 192  # the rest of the tokens go to the candidate


def training_lengths(model_id: str) -> tuple[int, int]:
    """(max_length, query_tokens) the model was trained with."""
    settings_file = Path(model_id) / "patchpilot.json"
    if not settings_file.exists():
        try:
            from huggingface_hub import hf_hub_download

            settings_file = Path(hf_hub_download(model_id, "patchpilot.json"))
        except Exception:  # not on the Hub, offline, or saved without the file
            return MAX_LENGTH, QUERY_TOKENS
    settings = json.loads(settings_file.read_text(encoding="utf-8"))
    return int(settings["max_length"]), int(settings["query_tokens"])


class CrossEncoderRanker:
    name = "cross_encoder"

    def __init__(self, model_id: str, batch_size: int = 16, scorer: Any = None) -> None:
        self.model_id = model_id
        self.batch_size = batch_size
        self._scorer = scorer  # tests inject a function (query, texts) -> scores
        self._model: Any = None
        self._tokenizer: Any = None
        self.max_length, self.query_tokens = MAX_LENGTH, QUERY_TOKENS

    def _load(self) -> None:
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        self.max_length, self.query_tokens = training_lengths(self.model_id)
        self._tokenizer = AutoTokenizer.from_pretrained(self.model_id)
        self._model = AutoModelForSequenceClassification.from_pretrained(self.model_id)
        self._model.eval()

    def scores(self, query: str, texts: Sequence[str]) -> list[float]:
        if self._scorer is not None:
            return list(self._scorer(query, list(texts)))
        if self._model is None:
            self._load()
        import torch

        query_ids = self._tokenizer(query, add_special_tokens=False)["input_ids"]
        short_query = self._tokenizer.decode(query_ids[: self.query_tokens])
        # Similar lengths share a batch, so little time goes into padding.
        order = sorted(range(len(texts)), key=lambda i: len(texts[i]))
        scores = [0.0] * len(texts)
        for start in range(0, len(order), self.batch_size):
            chunk = order[start : start + self.batch_size]
            encoded = self._tokenizer(
                [short_query] * len(chunk),
                [texts[i] for i in chunk],
                truncation="only_second",
                max_length=self.max_length,
                padding=True,
                return_tensors="pt",
            )
            with torch.no_grad():
                logits = self._model(**encoded).logits
            # One logit -> use it; two logits -> probability of the "buggy" class.
            if logits.shape[-1] == 1:
                batch_scores = logits[:, 0].tolist()
            else:
                batch_scores = torch.softmax(logits, dim=-1)[:, 1].tolist()
            for i, score in zip(chunk, batch_scores, strict=True):
                scores[i] = score
        return scores

    def rank(
        self, query: str, doc_ids: Sequence[str], texts: Sequence[str]
    ) -> list[tuple[str, float]]:
        scored = list(zip(doc_ids, self.scores(query, texts), strict=True))
        return sorted(scored, key=lambda pair: -pair[1])
