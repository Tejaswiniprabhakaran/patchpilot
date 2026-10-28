import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from patchpilot.localization.cross_encoder import (
    MAX_LENGTH,
    QUERY_TOKENS,
    CrossEncoderRanker,
    training_lengths,
)


def test_training_lengths_come_from_the_saved_settings(tmp_path: Path) -> None:
    (tmp_path / "patchpilot.json").write_text(json.dumps({"max_length": 256, "query_tokens": 128}))

    assert training_lengths(str(tmp_path)) == (256, 128)


def test_models_saved_without_settings_use_the_notebook_lengths(tmp_path: Path) -> None:
    assert training_lengths(str(tmp_path / "no-settings")) == (MAX_LENGTH, QUERY_TOKENS)


class FakeTokenizer:
    """Tokens are characters; a batch is returned as the texts themselves."""

    def __call__(self, first: Any, second: Any = None, **kwargs: Any) -> dict[str, Any]:
        if second is None:
            return {"input_ids": list(first)}
        return {"texts": second}

    def decode(self, ids: list[str]) -> str:
        return "".join(ids)


def test_scores_stay_in_input_order_although_batches_are_sorted_by_length() -> None:
    torch = pytest.importorskip("torch")
    batches: list[list[str]] = []

    def model(texts: list[str]) -> SimpleNamespace:
        batches.append(texts)
        # Two logits; the "buggy" logit grows with the text length.
        logits = torch.tensor([[0.0, float(len(t))] for t in texts])
        return SimpleNamespace(logits=logits)

    ranker = CrossEncoderRanker("unused", batch_size=2)
    ranker._tokenizer, ranker._model = FakeTokenizer(), model
    texts = ["aaaa", "a", "aaaaaaa", "aa", "aaaaa"]

    scores = ranker.scores("query", texts)

    assert batches == [["a", "aa"], ["aaaa", "aaaaa"], ["aaaaaaa"]]
    assert sorted(range(len(texts)), key=lambda i: scores[i]) == [1, 3, 0, 4, 2]
    assert ranker.rank("query", ["w", "x", "y", "z", "v"], texts)[0][0] == "y"
