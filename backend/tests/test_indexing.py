"""implementation-plan.md Step 6 — re-derives rag-pipeline.md §4's original
4-query retrieval smoke test as a real automated test. The exact original
queries were never saved (same gap as steps 3 and 5's fixtures), except
one preserved verbatim in the docs ("what citation style should I
choose") — reused here. The other three are newly constructed against the
same real fixture content, verified by reading the actual extracted text
first, not guessed.

Needs tests/fixtures/ingestion/ (scripts/fetch_ingestion_fixtures.py) and
models/bge-small-en-v1.5-onnx/ (scripts/convert_embedding_model.py).
"""

import tempfile
from pathlib import Path

import pytest

import ingestion
import indexing

FIXTURES = Path(__file__).parent / "fixtures" / "ingestion"

pytestmark = pytest.mark.skipif(
    not FIXTURES.exists() or not (Path(__file__).parent.parent / "models").exists(),
    reason="run scripts/fetch_ingestion_fixtures.py and scripts/convert_embedding_model.py first",
)


@pytest.fixture(scope="module")
def retriever():
    nodes = []

    zotero_pages = ingestion.extract_pdf(FIXTURES / "sprint3_zotero_tutorial.pdf")
    for p in zotero_pages:
        if p["needs_fallback"]:
            p["text"] = ingestion.ocr_pdf_page(FIXTURES / "sprint3_zotero_tutorial.pdf", p["page"])
    nodes += indexing.pages_to_nodes(zotero_pages, "zotero")

    slides = ingestion.extract_pptx(FIXTURES / "sprint3_ai_research.pptx")
    nodes += indexing.slides_to_nodes(slides, "ai_research")

    nodes += indexing.pages_to_nodes(ingestion.extract_pdf(FIXTURES / "research_study.pdf"), "research_study")
    nodes += indexing.pages_to_nodes(ingestion.extract_pdf(FIXTURES / "literature_review.pdf"), "literature_review")

    with tempfile.TemporaryDirectory() as tmp:
        index = indexing.build_index(nodes, Path(tmp), "smoke_test")
        yield index.as_retriever(similarity_top_k=3)


def _hit_rank(results, source, expected_pages):
    for i, r in enumerate(results, 1):
        anchor = r.metadata.get("page") or r.metadata.get("slide")
        if r.metadata.get("source") == source and anchor in expected_pages:
            return i
    return None


# rag-pipeline.md §4's key finding: OCR-recovered text (page 8's plain-text
# extraction is too sparse to answer this — density-heuristic-flagged, see
# tests/fixtures/ingestion_baseline.json) is still good enough as embedding
# input for correct, top-ranked retrieval.
def test_ocr_dependent_query_ranks_first(retriever):
    results = retriever.retrieve("What citation style should I choose?")
    assert _hit_rank(results, "zotero", {8}) == 1


# Pages 3 and 4 are genuine near-duplicates (both titled "Installation",
# near-identical opening text) — either is a correct answer.
def test_install_query_hits_top_3(retriever):
    results = retriever.retrieve("How do I install Zotero?")
    assert _hit_rank(results, "zotero", {3, 4}) is not None


def test_collection_query_hits_top_3(retriever):
    results = retriever.retrieve("How do I create a collection in Zotero?")
    assert _hit_rank(results, "zotero", {5}) is not None


def test_cross_file_query_hits_top_3(retriever):
    results = retriever.retrieve("What is NVIDIA NeMo Retriever?")
    assert _hit_rank(results, "ai_research", {9}) is not None
