"""implementation-plan.md Step 5. Needs the real course files fetched by
scripts/fetch_ingestion_fixtures.py — not committed (an instructor's
actual course materials, not ours to redistribute; see .gitignore). The
measured baseline derived from them *is* committed
(tests/fixtures/ingestion_baseline.json) — numbers only, no extracted text.

sprint3_zotero_tutorial.pdf and sprint3_ai_research.pptx are confirmed to
be the exact files Sprint 3 measured (matching page/slide counts and
character ranges almost exactly, including the 5.5.3-vs-original-version
OCR noise) — this is a real regression test against historical numbers,
not a fresh baseline pretending to be one.
"""

import json
from pathlib import Path

import pytest

import ingestion

FIXTURES = Path(__file__).parent / "fixtures" / "ingestion"
BASELINE = json.loads((Path(__file__).parent / "fixtures" / "ingestion_baseline.json").read_text())

pytestmark = pytest.mark.skipif(
    not FIXTURES.exists(), reason="run scripts/fetch_ingestion_fixtures.py first"
)


def test_zotero_pdf_matches_sprint3_plain_text():
    expected = BASELINE["sprint3_zotero_tutorial.pdf"]
    pages = ingestion.extract_pdf(FIXTURES / "sprint3_zotero_tutorial.pdf")
    assert len(pages) == expected["pages"]
    assert [p["char_count"] for p in pages] == expected["char_counts"]
    assert [p["needs_fallback"] for p in pages] == expected["flagged"]


def test_zotero_pdf_ocr_matches_sprint3_recovery():
    expected = BASELINE["sprint3_zotero_tutorial.pdf"]["ocr_total_chars"]
    total = sum(len(ingestion.ocr_pdf_page(FIXTURES / "sprint3_zotero_tutorial.pdf", i)) for i in range(1, 12))
    # OCR isn't bit-for-bit deterministic across Tesseract versions/runs —
    # assert it's in the ballpark of the historical ~3x recovery, not exact.
    assert abs(total - expected) / expected < 0.05


def test_ai_research_pptx_matches_sprint3():
    expected = BASELINE["sprint3_ai_research.pptx"]
    slides = ingestion.extract_pptx(FIXTURES / "sprint3_ai_research.pptx")
    assert len(slides) == expected["slides"]
    assert [s["char_count"] for s in slides] == expected["char_counts"]
    assert [s["has_image"] for s in slides] == expected["has_image"]


@pytest.mark.parametrize("filename", ["research_study.pdf", "literature_review.pdf"])
def test_academic_pdfs_match_baseline(filename):
    expected = BASELINE[filename]
    pages = ingestion.extract_pdf(FIXTURES / filename)
    assert len(pages) == expected["pages"]
    assert [p["char_count"] for p in pages] == expected["char_counts"]
    assert [p["needs_fallback"] for p in pages] == expected["flagged"]
