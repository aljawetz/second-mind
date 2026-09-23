"""ingestion.merge_ocr_text — OCR adds to a page's own text, never replaces it.

The inputs are real pairs from 18-654's course-info slides (native PDF text
vs Tesseract output for the same page). Replacing the native text with OCR
is what taught the chat that the grading slide said only "12.5% 17.5%" and
that the final was on "December 2"4" — see
docs/evaluations/2026-09-23-ask-modes/report.md."""

import ingestion

GRADING_NATIVE = (
    "Grading Rubric\n12.5% Project\n17.5% Labs\n30% Assignments\n20% Midterm Exam\n20% Final Exam\n"
    "Deductions for failure to complete a few required chores"
)
GRADING_OCR = "Grading Rubric\n\n12.5%\n17.5%\n\nDeductions for failure to complete a few required chores\n\n"

EXAM_NATIVE = (
    "Exams (x2: 20 + 20 = 40%)\n• Midterm: Wednesday, October 7th\n• Final: Wednesday, December 2nd\n• Closed book"
)
EXAM_OCR = (
    "fe\nExams (x2: 20 + 20 = 40%) Ea\nCALENDAR’\n\nMidterm: | Wednesday, October 7‘\n"
    'Final: Wednesday, December 2"4\n\nClosed book\n'
)

# A concept-map slide: the title is real text, the map itself is an image.
MAP_NATIVE = "DevOps - runtime concept map\nSource: a Survey of DevOps Concepts and Challenges, Leite et al. 2019"
MAP_OCR = (
    "DevOps - runtime concept map\n\nSecurity\nStability\n\nprovides opportunities and\n\n"
    "Infrastructure as code imposes challenges to\n\nVirtualization\nContainerization\nCloud services\n\n"
    "Business metrics\nResource metrics\nAlerting\n"
)


def test_native_text_is_kept_when_ocr_loses_words():
    merged = ingestion.merge_ocr_text(GRADING_NATIVE, GRADING_OCR)
    assert merged == GRADING_NATIVE


def test_ocr_misreadings_of_existing_lines_are_not_added():
    merged = ingestion.merge_ocr_text(EXAM_NATIVE, EXAM_OCR)
    assert "December 2nd" in merged
    assert '2"4' not in merged
    assert merged == EXAM_NATIVE


def test_ocr_lines_with_new_words_are_added_and_marked():
    merged = ingestion.merge_ocr_text(MAP_NATIVE, MAP_OCR)
    assert merged.startswith(MAP_NATIVE)
    assert ingestion.OCR_MARKER in merged
    for line in ("Infrastructure as code imposes challenges to", "Containerization", "Business metrics"):
        assert line in merged
    # The title OCR re-read is already in the native text, so it isn't repeated.
    assert merged.count("DevOps - runtime concept map") == 1


def test_a_few_stray_ocr_words_are_not_worth_adding():
    native = "Submission of Reports/Assignments\nCanvas"
    ocr = "ate\nd- -@\nWoe\n\nCanvas\n\nvocareum\n"
    assert ingestion.merge_ocr_text(native, ocr) == native


def test_ocr_is_used_alone_when_the_page_has_no_text_of_its_own():
    ocr = "It's a tool-rich course!\neclipse JUnit Mockito\nJaCoCo Java Code Coverage\nTestcontainers SpotBugs docker"
    assert ingestion.merge_ocr_text("", ocr) == ocr.strip()
    assert ingestion.merge_ocr_text("  \n ", ocr) == ocr.strip()


def test_empty_ocr_keeps_native_text():
    assert ingestion.merge_ocr_text("Upcoming Monday", "") == "Upcoming Monday"
