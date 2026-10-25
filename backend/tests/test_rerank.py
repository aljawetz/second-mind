"""Reranking in HybridRetriever (Sprint 8 PR 3). Stand-in reranker and
index, so only the ordering, cutoff and fallback logic is tested here. The
last test uses the real model and is skipped when it is not converted."""

import pytest
from llama_index.core.schema import NodeWithScore, QueryBundle, TextNode

import generation
import reranker
from generation import HybridRetriever, rerank


def _n(node_id, score=0.5):
    return NodeWithScore(node=TextNode(id_=node_id, text=node_id), score=score)


def _ids(nodes):
    return [n.node.node_id for n in nodes]


class _FakeReranker:
    """Scores each passage by a fixed table keyed on its text."""

    def __init__(self, scores):
        self.scores = scores
        self.calls = []

    def score(self, query, passages):
        self.calls.append((query, list(passages)))
        return [self.scores.get(p, 0.0) for p in passages]


class _BrokenReranker:
    def score(self, query, passages):
        raise RuntimeError("onnx session died")


def test_rerank_orders_by_reranker_score():
    nodes = [_n("a"), _n("b"), _n("c")]
    result = rerank(_FakeReranker({"a": 0.2, "b": 0.9, "c": 0.5}), "q", nodes, top_n=5, min_score=0.0)
    assert _ids(result) == ["b", "c", "a"]


def test_rerank_score_replaces_the_original_score():
    result = rerank(_FakeReranker({"a": 0.7}), "q", [_n("a", 12.5)], top_n=5, min_score=0.0)
    assert result[0].score == pytest.approx(0.7)


def test_rerank_drops_results_under_the_minimum_score():
    nodes = [_n("a"), _n("b"), _n("c")]
    result = rerank(_FakeReranker({"a": 0.5, "b": 0.01, "c": 0.3}), "q", nodes, top_n=5, min_score=0.1)
    assert _ids(result) == ["a", "c"]


def test_rerank_keeps_a_result_exactly_at_the_minimum():
    assert _ids(rerank(_FakeReranker({"a": 0.1}), "q", [_n("a")], top_n=5, min_score=0.1)) == ["a"]


def test_rerank_returns_nothing_when_all_are_weak():
    nodes = [_n("a"), _n("b")]
    assert rerank(_FakeReranker({"a": 0.01, "b": 0.02}), "q", nodes, top_n=5, min_score=0.1) == []


def test_rerank_cuts_to_top_n():
    nodes = [_n(str(i)) for i in range(20)]
    scores = {str(i): i / 20 for i in range(20)}
    assert _ids(rerank(_FakeReranker(scores), "q", nodes, top_n=5, min_score=0.0)) == ["19", "18", "17", "16", "15"]


def test_rerank_ties_keep_fusion_order():
    nodes = [_n("a"), _n("b"), _n("c")]
    assert _ids(rerank(_FakeReranker({"a": 0.5, "b": 0.5, "c": 0.5}), "q", nodes, top_n=5, min_score=0.0)) == ["a", "b", "c"]


def test_rerank_of_nothing_does_not_call_the_model():
    fake = _FakeReranker({})
    assert rerank(fake, "q", [], top_n=5, min_score=0.0) == []
    assert fake.calls == []


def test_rerank_falls_back_to_fusion_order_if_the_model_fails():
    nodes = [_n(str(i)) for i in range(8)]
    assert _ids(rerank(_BrokenReranker(), "q", nodes, top_n=5, min_score=0.5)) == ["0", "1", "2", "3", "4"]


class _Table:
    def __init__(self, rows):
        self._rows = rows

    def search(self, _query, query_type):
        return self

    def limit(self, n):
        return self

    def to_pandas(self):
        import pandas as pd

        return pd.DataFrame(self._rows, columns=["metadata", "_score"])


class _Index:
    def __init__(self, vector_nodes, fts_rows):
        self._vector_nodes = vector_nodes
        self.vector_store = type("VS", (), {"table": _Table(fts_rows)})()

    def as_retriever(self, similarity_top_k):
        nodes = self._vector_nodes

        class _R:
            def retrieve(self, _q):
                return list(nodes)

        return _R()


def _fts_row(node_id):
    return {"metadata": {"id": node_id}, "_score": 3.0}


@pytest.fixture(autouse=True)
def _simple_fts_nodes(monkeypatch):
    monkeypatch.setattr(generation, "metadata_dict_to_node", lambda meta: TextNode(id_=meta["id"], text=meta["id"]))


def test_retriever_reranks_a_pool_larger_than_top_k():
    vector = [_n(f"v{i}", 0.9) for i in range(15)]
    index = _Index(vector, [_fts_row(f"k{i}") for i in range(10)])
    fake = _FakeReranker({"k9": 0.95, "v9": 0.9})
    result = HybridRetriever(index, similarity_cutoff=0.0, reranker=fake, rerank_candidates=20, rerank_min_score=0.5).retrieve(
        QueryBundle("q")
    )
    assert len(fake.calls[0][1]) == 20
    # Both were outside the fusion top 5; only the reranker brings them up.
    assert _ids(result) == ["k9", "v9"]


def test_retriever_without_a_reranker_is_fusion_only():
    vector = [_n(f"v{i}", 0.9) for i in range(10)]
    index = _Index(vector, [])
    result = HybridRetriever(index, similarity_cutoff=0.0, reranker=None).retrieve(QueryBundle("q"))
    assert _ids(result) == [f"v{i}" for i in range(5)]


def test_retriever_with_no_candidates_returns_nothing():
    fake = _FakeReranker({})
    assert HybridRetriever(_Index([], []), reranker=fake).retrieve(QueryBundle("q")) == []


@pytest.mark.real_reranker
def test_missing_model_files_mean_no_reranker(tmp_path):
    assert reranker.load_reranker(tmp_path) is None


@pytest.mark.real_reranker
def test_real_model_prefers_the_answering_passage():
    model = reranker.load_reranker()
    if model is None:
        pytest.skip("reranker model not converted (scripts/convert_reranker_model.py)")
    scores = model.score(
        "When is the midterm exam?",
        ["The midterm exam is on Tuesday October 14 in class.", "Genetic algorithms use mutation and crossover."],
    )
    assert all(0.0 <= s <= 1.0 for s in scores)
    assert scores[0] > scores[1]
