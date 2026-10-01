import pytest

from patchpilot.localization.bm25 import BM25Ranker, document_text, tokenize
from patchpilot.localization.metrics import first_hit_rank, summarise, top_k_accuracy


def test_tokenize_splits_identifiers_and_drops_stopwords() -> None:
    tokens = tokenize("def parse_HTTPHeader(self): return the getValue")

    assert "parse" in tokens
    assert "http" in tokens
    assert "header" in tokens
    assert "httpheader" in tokens
    assert "getvalue" in tokens and "get" in tokens and "value" in tokens
    assert "the" not in tokens and "self" not in tokens and "def" not in tokens


def test_bm25_ranks_the_matching_document_first() -> None:
    ranker = BM25Ranker(
        ["a.py", "b.py", "c.py"],
        [
            document_text("a.py", "def render_template(): pass"),
            document_text("b.py", "def parse_header(raw): split header lines"),
            document_text("c.py", "def connect_db(): pass"),
        ],
    )

    ranking = [doc for doc, _ in ranker.rank("Header parsing fails on folded header lines")]

    assert ranking[0] == "b.py"


def test_bm25_rejects_mismatched_inputs() -> None:
    with pytest.raises(ValueError):
        BM25Ranker(["a"], [])


def test_rank_metrics() -> None:
    ranks = [first_hit_rank(["x", "g"], ["g"]), first_hit_rank(["g"], ["g"]), None]

    assert ranks == [2, 1, None]
    assert top_k_accuracy(ranks, 1) == pytest.approx(1 / 3)
    assert summarise(ranks) == {"top1": 0.3333, "top3": 0.6667, "top5": 0.6667, "mrr": 0.5, "n": 3}
    assert summarise([]) == {"top1": 0.0, "top3": 0.0, "top5": 0.0, "mrr": 0.0, "n": 0}
