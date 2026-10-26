"""Rank fusion in HybridRetriever (Sprint 8). No index, no network: small
stand-in nodes and a stand-in index so only the merge logic is tested."""

import pandas as pd
from llama_index.core.schema import NodeWithScore, QueryBundle, TextNode

import generation
from generation import HybridRetriever, reciprocal_rank_fusion


def _n(node_id, score=0.5):
    return NodeWithScore(node=TextNode(id_=node_id, text=node_id), score=score)


def _ids(nodes):
    return [n.node.node_id for n in nodes]


def test_node_in_both_lists_ranks_first():
    vector = [_n("a"), _n("b"), _n("c")]
    keyword = [_n("c"), _n("d")]
    # c: 1/63 + 1/61, a: 1/61, d: 1/62, b: 1/62. Ties keep first-seen order.
    assert _ids(reciprocal_rank_fusion([vector, keyword], k=60, top_n=5)) == ["c", "a", "b", "d"]


def test_fusion_uses_rank_not_raw_score():
    vector = [_n("a", 0.9), _n("b", 0.8)]
    keyword = [_n("b", 40.0)]
    assert _ids(reciprocal_rank_fusion([vector, keyword])) == ["b", "a"]


def test_duplicates_are_kept_once_with_their_first_score():
    vector = [_n("a", 0.7), _n("a", 0.6)]
    keyword = [_n("a", 12.0)]
    fused = reciprocal_rank_fusion([vector, keyword])
    assert _ids(fused) == ["a"]
    assert fused[0].score == 0.7


def test_top_n_cuts_the_list():
    vector = [_n(str(i)) for i in range(20)]
    assert len(reciprocal_rank_fusion([vector, []], top_n=5)) == 5


def test_empty_inputs_give_empty_result():
    assert reciprocal_rank_fusion([]) == []
    assert reciprocal_rank_fusion([[], []]) == []


class _Table:
    def __init__(self, rows):
        self._rows = rows

    def search(self, _query, query_type):
        assert query_type == "fts"
        return self

    def limit(self, n):
        self.limit_used = n
        return self

    def to_pandas(self):
        return pd.DataFrame(self._rows, columns=["metadata", "_score"])


class _Index:
    def __init__(self, vector_nodes, fts_rows):
        self._vector_nodes = vector_nodes
        self.vector_store = type("Store", (), {"table": _Table(fts_rows)})()
        self.top_k_used = None

    def as_retriever(self, similarity_top_k):
        self.top_k_used = similarity_top_k
        nodes = self._vector_nodes
        return type("R", (), {"retrieve": lambda _self, _q: list(nodes)})()


def _patch_metadata(monkeypatch):
    monkeypatch.setattr(generation, "metadata_dict_to_node", lambda meta: TextNode(id_=meta["id"], text=meta["id"]))


def test_keyword_only_hit_surfaces(monkeypatch):
    _patch_metadata(monkeypatch)
    vector = [_n(f"v{i}", 0.9 - i * 0.01) for i in range(8)]
    index = _Index(vector, [({"id": "kw"}, 7.5)])
    result = HybridRetriever(index, similarity_cutoff=0.0).retrieve(QueryBundle("Mockito"))
    assert "kw" in _ids(result)
    assert len(result) == 5
    kw = next(n for n in result if n.node.node_id == "kw")
    assert kw.score == 7.5  # keeps its own score


def test_retriever_fetches_more_candidates_and_dedupes(monkeypatch):
    _patch_metadata(monkeypatch)
    index = _Index([_n("a", 0.9), _n("b", 0.8)], [({"id": "b"}, 3.0), ({"id": "c"}, 2.0)])
    result = HybridRetriever(index, similarity_cutoff=0.0).retrieve(QueryBundle("q"))
    assert _ids(result) == ["b", "a", "c"]
    assert index.top_k_used == generation.VECTOR_CANDIDATES == 20
    assert index.vector_store.table.limit_used == generation.FTS_TOP_K == 10


def test_retriever_with_no_hits_returns_nothing(monkeypatch):
    _patch_metadata(monkeypatch)
    index = _Index([], [])
    assert HybridRetriever(index).retrieve(QueryBundle("nothing")) == []
