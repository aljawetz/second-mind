"""Search-only eval (ask_modes_eval.py --retrieval-only).

A tiny LanceDB index in a temp dir, with a local stand-in for the embedding
model. No API key and no network: the scores come from HybridRetriever and
from the same recall@5 / precision@5 helpers the Sprint 7 chat run uses.
"""

import importlib.util
import json
import re
import sys
from pathlib import Path

import numpy as np
import pytest
from llama_index.core import StorageContext, VectorStoreIndex
from llama_index.core.embeddings import BaseEmbedding
from llama_index.core.schema import NodeWithScore, TextNode
from llama_index.vector_stores.lancedb import LanceDBVectorStore

import generation
import indexing
from embeddings import EMBEDDING_DIM

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "ask_modes_eval.py"


def _load_eval():
    spec = importlib.util.spec_from_file_location("ask_modes_eval", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["ask_modes_eval"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def eval_mod():
    return _load_eval()


class _HashEmbedding(BaseEmbedding):
    """Bag of words, hashed into the real embedding width. Offline, and
    stable for one process. Vector scores stay under the 0.5 cutoff on this
    tiny set, so HybridRetriever's keyword hit is what comes back."""

    def _embed(self, text: str) -> list[float]:
        vec = np.zeros(EMBEDDING_DIM, dtype=np.float64)
        tokens = re.findall(r"[a-z0-9]+", text.lower()) or ["empty"]
        for token in tokens:
            slot = 0
            for char in token:
                slot = (slot * 33 + ord(char)) % EMBEDDING_DIM
            vec[slot] += 1.0
        vec /= np.linalg.norm(vec)
        return vec.tolist()

    def _get_query_embedding(self, query: str) -> list[float]:
        return self._embed(query)

    def _get_text_embedding(self, text: str) -> list[float]:
        return self._embed(text)

    def _get_text_embeddings(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    async def _aget_query_embedding(self, query: str) -> list[float]:
        return self._embed(query)

    async def _aget_text_embedding(self, text: str) -> list[float]:
        return self._embed(text)


def _nodes():
    pages = [
        ("The final exam is worth 20 percent of the grade.", "syllabus", 2),
        ("Project teams may include at most five students.", "01 CourseInfoF26.pdf", 28),
        ("Office hours are Tuesday afternoons in the lab.", "calendar.pdf", 1),
        ("Stubs return canned answers. Mocks verify calls.", "06 Isolating Components - Test Doubles.pdf", 4),
        ("Combinatorial testing covers pairs of input blocks.", "08 - CombinatorialTesting.pdf", 1),
        ("Late work loses ten percent per day.", "syllabus", 9),
    ]
    nodes = []
    for text, source, page in pages:
        nodes.append(
            TextNode(
                text=text,
                metadata={"source": source, "item_type": "file", "page": page, "slide": None, "timestamp": None},
            )
        )
    return nodes


@pytest.fixture
def index(tmp_path):
    store = LanceDBVectorStore(uri=str(tmp_path / "index.lancedb"), table_name="course_55710")
    built = VectorStoreIndex(
        _nodes(),
        storage_context=StorageContext.from_defaults(vector_store=store),
        embed_model=_HashEmbedding(),
        transformations=[],
    )
    indexing.ensure_fts_index(store.table)
    return built


def _case(case_id, question, gold_source, course=55710, **extra):
    case = {
        "id": case_id,
        "course": course,
        "kind": "course_fact",
        "turns": [question],
        "gold_source": gold_source,
    }
    case.update(extra)
    return case


def _node(source: str, text: str, page: int = 1) -> NodeWithScore:
    node = TextNode(text=text, metadata={"source": source, "item_type": "file", "page": page})
    return NodeWithScore(node=node, score=0.9)


def test_shipped_retriever_matches_hybrid_retriever(eval_mod, index):
    question = "How much is the final exam worth?"
    shipped = eval_mod.shipped_retriever(index).retrieve(question)
    direct = generation.HybridRetriever(index).retrieve(question)

    assert [n.node.get_content() for n in shipped] == [n.node.get_content() for n in direct]
    assert shipped
    assert "syllabus" in generation.build_citations(shipped)[0]["label"]


def test_search_only_scores_recall_and_precision_on_the_fixture_index(eval_mod, index):
    cases = [
        _case("HIT", "How much is the final exam worth?", "syllabus"),
        _case("MISS", "How many people can be on a project team?", "syllabus"),
        _case("NONE", "What is my grade?", None, kind="not_in_course"),
    ]

    report = eval_mod.evaluate_retrieval(cases, lambda _course: index)
    by_id = {row["case"]: row for row in report["results"]}

    assert by_id["HIT"]["recall_at_5"] is True
    assert by_id["HIT"]["precision_at_5"] == 1.0
    assert any("syllabus" in label for label in by_id["HIT"]["retrieved"])

    assert by_id["MISS"]["recall_at_5"] is False
    assert by_id["MISS"]["precision_at_5"] == 0.0
    assert by_id["MISS"]["retrieved"]
    assert all("syllabus" not in label for label in by_id["MISS"]["retrieved"])

    assert by_id["NONE"]["recall_at_5"] is None
    assert by_id["NONE"]["precision_at_5"] is None

    # NONE has no expected source, so it stays out of both averages.
    assert report["metrics"] == {
        "n": 3,
        "n_recall": 2,
        "n_precision": 2,
        "recall_at_5": 0.5,
        "precision_at_5": 0.5,
    }


def test_a_replacement_retriever_is_scored_the_same_way(eval_mod, index):
    """The hook later rerank and query-rewrite stages plug into."""
    built = []

    class RewriteThenSearch:
        def __init__(self, course_index):
            built.append(course_index)
            self._inner = generation.HybridRetriever(course_index)

        def retrieve(self, query):
            if query == "zzzz-query":
                query = "How much is the final exam worth?"
            return self._inner.retrieve(query)

    case = _case("Q", "zzzz-query", "syllabus")
    plain = eval_mod.evaluate_retrieval([case], lambda _course: index)
    rewritten = eval_mod.evaluate_retrieval([case], lambda _course: index, retriever_for=RewriteThenSearch)

    assert plain["results"][0]["recall_at_5"] is False
    assert plain["results"][0]["precision_at_5"] is None
    assert rewritten["results"][0]["recall_at_5"] is True
    assert rewritten["results"][0]["precision_at_5"] == 1.0
    assert built == [index]


def test_several_acceptable_sources_count_for_precision_only(eval_mod, index):
    """precision_at_k honors gold_sources. recall_at_5 stays on gold_source.
    That split is the Sprint 7 definition."""

    class Fixed:
        def __init__(self, _index):
            pass

        def retrieve(self, _query):
            return [_node("calendar.pdf", "office hours")]

    case = _case("ALT", "When are office hours?", "syllabus", gold_sources=["calendar.pdf"])
    row = eval_mod.evaluate_retrieval([case], lambda _course: index, retriever_for=Fixed)["results"][0]

    assert row["recall_at_5"] is False
    assert row["precision_at_5"] == 1.0


def test_precision_is_the_share_of_returned_sources_that_match(eval_mod, index):
    class FiveSources:
        def __init__(self, _index):
            pass

        def retrieve(self, _query):
            return [
                _node("syllabus", "final exam"),
                _node("other.pdf", "other"),
                _node("syllabus", "grading"),
                _node("notes.pdf", "notes"),
                _node("calendar.pdf", "hours"),
            ]

    case = _case("MIX", "How much is the final exam worth?", "syllabus")
    row = eval_mod.evaluate_retrieval([case], lambda _course: index, retriever_for=FiveSources)["results"][0]

    assert row["recall_at_5"] is True
    assert row["precision_at_5"] == 0.4
    assert len(row["retrieved"]) == 5


def test_retriever_is_built_once_per_course(eval_mod, index):
    seen = []

    class Counting:
        def __init__(self, course_index):
            seen.append(course_index)

        def retrieve(self, _query):
            return []

    cases = [
        _case("A", "one", "syllabus", course=55710),
        _case("B", "two", "syllabus", course=55710),
        _case("C", "three", "syllabus", course=56350),
    ]
    eval_mod.evaluate_retrieval(cases, lambda _course: index, retriever_for=Counting)

    assert seen == [index, index]


def test_cli_writes_results_and_does_not_open_an_api_client(eval_mod, index, tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    def refuse(*_args, **_kwargs):
        raise AssertionError("search-only eval must not open an API client")

    monkeypatch.setattr(eval_mod.providers, "openai_client", refuse)
    monkeypatch.setattr(eval_mod.providers, "api_key", refuse)
    monkeypatch.setattr(eval_mod.indexing, "load_index", lambda _path, _table: index)

    out = tmp_path / "retrieval-before.json"
    monkeypatch.setattr(
        sys,
        "argv",
        ["ask_modes_eval.py", "--set", "sprint7", "--cases", "F2", "--retrieval-only", "--out", str(out)],
    )
    eval_mod.main()

    report = json.loads(out.read_text())
    assert report["mode"] == "retrieval-only"
    assert report["set"] == "sprint7"
    assert report["index"].endswith("index.lancedb")
    assert report["metrics"]["n"] == 1
    assert report["metrics"]["recall_at_5"] == 1.0
    assert report["metrics"]["precision_at_5"] == 1.0
    assert report["results"][0]["case"] == "F2"
    assert report["results"][0]["question"] == "How much is the final exam worth?"
    assert report["results"][0]["recall_at_5"] is True
    assert "syllabus" in report["results"][0]["retrieved"][0]

    printed = capsys.readouterr().out
    assert "| F2.1 | yes | 100% |" in printed
    assert "| 1 | 100% | 100% |" in printed
    assert "Sprint 7 shipped chat baseline: recall@5 73%, precision@5 22%." in printed


def test_oracle_retriever_scores_perfect_recall_and_precision(eval_mod, index):
    """A searcher that always hands back the expected source scores 100%."""
    expected = {case["turns"][0]: case["gold_source"] for case in eval_mod.SAMPLE_CASES}

    class Oracle:
        def __init__(self, _index):
            pass

        def retrieve(self, query):
            return [_node(expected[query], "the page the question is about")]

    report = eval_mod.evaluate_retrieval(eval_mod.SAMPLE_CASES, lambda _course: index, retriever_for=Oracle)

    assert report["metrics"]["recall_at_5"] == 1.0
    assert report["metrics"]["precision_at_5"] == 1.0
    assert report["metrics"]["n_recall"] == len(eval_mod.SAMPLE_CASES)
    assert all(row["recall_at_5"] is True and row["precision_at_5"] == 1.0 for row in report["results"])


def test_empty_retriever_scores_zero_recall(eval_mod, index, capsys):
    """A searcher that returns nothing scores 0% recall. Precision stays
    blank: the Sprint 7 definition has no share to take when a search
    returns no sources."""

    class Empty:
        def __init__(self, _index):
            pass

        def retrieve(self, _query):
            return []

    report = eval_mod.evaluate_retrieval(eval_mod.SAMPLE_CASES, lambda _course: index, retriever_for=Empty)

    assert report["metrics"]["recall_at_5"] == 0.0
    assert report["metrics"]["precision_at_5"] is None
    assert report["metrics"]["n_recall"] == len(eval_mod.SAMPLE_CASES)
    assert report["metrics"]["n_precision"] == 0
    assert all(row["recall_at_5"] is False and row["retrieved"] == [] for row in report["results"])

    report["set"] = "sample"
    eval_mod.print_retrieval_report(report)
    assert "| 4 | 0% | n/a |" in capsys.readouterr().out


def test_cli_records_the_sample_set_and_index_path(eval_mod, index, tmp_path, monkeypatch):
    monkeypatch.setattr(eval_mod.indexing, "load_index", lambda _path, _table: index)
    monkeypatch.setattr(eval_mod.providers, "openai_client", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("api")))
    out = tmp_path / "out.json"
    index_path = tmp_path / "sample.lancedb"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "ask_modes_eval.py",
            "--set",
            "sample",
            "--retrieval-only",
            "--index",
            str(index_path),
            "--out",
            str(out),
        ],
    )
    eval_mod.main()
    report = json.loads(out.read_text())
    assert report["set"] == "sample"
    assert report["index"] == str(index_path)
    assert [row["case"] for row in report["results"]] == ["S1", "S2", "S3", "S4"]


MODEL_ONNX = Path(__file__).resolve().parent.parent / "models" / "bge-small-en-v1.5-onnx" / "model.onnx"


def _load_builder():
    path = Path(__file__).resolve().parent.parent / "scripts" / "make_sample_index.py"
    spec = importlib.util.spec_from_file_location("make_sample_index", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.skipif(not MODEL_ONNX.exists(), reason="run scripts/convert_embedding_model.py first")
def test_sample_course_search_finds_the_three_real_files(eval_mod, tmp_path):
    db = _load_builder().build_sample_index(tmp_path / "index.lancedb")

    def index_for(course_id):
        return indexing.load_index(db, f"course_{course_id}")

    report = eval_mod.evaluate_retrieval(eval_mod.SAMPLE_CASES, index_for)
    by_id = {row["case"]: row for row in report["results"]}

    assert by_id["S1"]["recall_at_5"] is True
    assert "exam-rules.txt" in by_id["S1"]["retrieved"][0]
    assert by_id["S2"]["recall_at_5"] is True
    assert "team-rules.txt" in by_id["S2"]["retrieved"][0]
    assert by_id["S3"]["recall_at_5"] is True
    assert "office-hours.txt" in by_id["S3"]["retrieved"][0]
    assert by_id["S4"]["recall_at_5"] is False
    assert all("animals.txt" not in label for label in by_id["S4"]["retrieved"])


def test_fixed_answer_keys_match_real_file_names():
    ev = _load_eval()
    recall_at_5, sprint7_cases = ev.recall_at_5, ev.sprint7_cases

    cases = {c["id"]: c for c in sprint7_cases()}
    zotero = [["Citation & Bibliography  with Zotero.pdf · p.9"]]
    for case_id in ("H13", "V7"):
        assert recall_at_5(cases[case_id]["gold_source"], zotero) is True
    primer = [["TDD Primer.pdf · p.1"]]
    for case_id in ("K4", "V6"):
        assert recall_at_5(cases[case_id]["gold_source"], primer) is True
