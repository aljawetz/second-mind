"""indexing.is_junk — near-empty and mostly-non-letter chunks are dropped
from Canvas material before indexing (RAG gaps plan, task 3). Thresholds
were set on the two local courses: 2 of 387 chunks fall under them
("Enjoy!", "Zotero"); the least-wordy real chunk, an Excel table of paper
statistics, has 30% letters and stays. A first version judged sections
without their heading and dropped "Syllabus › Units\n- 12", the answer to
"how many units is this course?" (sprint9-chat N5.3)."""

import pytest

import indexing


@pytest.mark.parametrize("text", ["- 12", "Enjoy!", "Zotero", "Thanks", "  \n ", "| 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 |", "2026-09-15 2026-09-22 2026-09-29"])
def test_short_or_mostly_non_letter_text_is_junk(text):
    assert indexing.is_junk(text)


@pytest.mark.parametrize(
    "text",
    [
        "12.5% | Project\n30% | Assignments",
        "Due Tue, Sep 15, 2026 at 10:00 AM EDT. Worth 100 points.",
        "Define the problem you want to address.",
        "Room GHC 4401",
        "Units\n- 12",
        "12.5% | Project",
        "| [22] | 30 | 30 | 34 |\nMössler et al. | [23] | 51 | 50 | 35",
    ],
)
def test_real_course_text_is_kept(text):
    assert not indexing.is_junk(text)


def test_junk_pages_are_dropped():
    pages = [{"page": 1, "text": "Enjoy!"}, {"page": 2, "text": "Boundary value analysis picks inputs at the edges."}]
    nodes = indexing.pages_to_nodes(pages, "BVA.pdf", "file:10")
    assert [n.metadata["page"] for n in nodes] == [2]


def test_junk_slides_are_dropped():
    slides = [{"slide": 1, "text": "Thanks"}, {"slide": 2, "text": "The test pyramid: many unit tests, few UI tests."}]
    nodes = indexing.slides_to_nodes(slides, "deck.pptx", "file:11")
    assert [n.metadata["slide"] for n in nodes] == [2]


def _section_texts(sections):
    return [n.text for n in indexing.sections_to_nodes(sections, "Syllabus", "syllabus:1", "syllabus")]


def test_a_short_value_under_its_heading_is_kept():
    assert _section_texts([{"heading": "Units", "text": "- 12"}]) == ["Syllabus › Units\n- 12"]


def test_a_section_is_judged_with_its_heading_but_not_the_document_title():
    sections = [
        {"heading": None, "text": "- 12"},
        {"heading": "Data", "text": "| 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 |"},
        {"heading": "Grading Algorithm", "text": "12.5% | Project\n30% | Assignments"},
    ]
    assert _section_texts(sections) == ["Syllabus › Grading Algorithm\n12.5% | Project\n30% | Assignments"]


def test_the_students_own_notes_and_transcripts_are_not_filtered():
    assert len(indexing.notes_to_nodes("HW due Fri", "Class #2", "session:1")) == 1
    segments = [{"start": 0.0, "end": 2.0, "text": "Okay."}]
    assert len(indexing.transcript_to_nodes(segments, "Class #2", "session:1")) == 1
