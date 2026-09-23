"""ingestion.extract_html_sections — Canvas HTML split at its own headings,
with tables kept as rows.

The shapes come from real syllabi: 18-654 marks sections with bold-only
paragraphs ("Grading Algorithm:") and puts the grading breakdown in a table;
18-658 uses <h4> headings, some of them inside table cells. Flattening all of
that into one line put the grading table in the same chunk as the staff list,
past the embedding model's 512-token window, where search never saw it."""

import ingestion

SYLLABUS_654 = """
<p><strong>Instructor: Rafal Wlodarski</strong></p>
<p>Office Hours: 2:00-3:00pm Mondays/Wednesday (room 104)</p>
<p><strong>Brief List of Topics</strong></p>
<ul><li><span>Testing Basics</span></li><li><span>Unit Testing</span></li></ul>
<p>&nbsp;</p>
<p><strong>Grading Algorithm:</strong></p>
<table border="1"><tbody>
<tr><td><p>12.5%</p></td><td><p>Project</p></td></tr>
<tr><td><p>17.5%</p></td><td><p>Labs</p></td></tr>
<tr><td><p>30%</p></td><td><p>Assignments</p></td></tr>
</tbody></table>
<p><strong>Late Work Penalty:</strong> late work within a grace period is accepted for some labs.</p>
"""

SYLLABUS_658 = """
<h4><strong>Grading Rubric</strong>&nbsp;</h4>
<p>Your grade is determined along two dimensions.</p>
<table><tbody>
<tr><td><strong>Component</strong></td><td><strong>Weight (%)</strong></td></tr>
<tr><td>Exam</td><td><h4><span>20</span></h4></td></tr>
<tr><td>Jama Lab</td><td><h4><span>5</span></h4></td></tr>
</tbody></table>
<h4><strong>Units</strong></h4>
<p>12</p>
"""


def _by_heading(html):
    return {s["heading"]: s["text"] for s in ingestion.extract_html_sections(html)}


def test_bold_only_paragraphs_start_sections():
    sections = _by_heading(SYLLABUS_654)
    assert list(sections) == ["Instructor: Rafal Wlodarski", "Brief List of Topics", "Grading Algorithm"]
    assert sections["Instructor: Rafal Wlodarski"] == "Office Hours: 2:00-3:00pm Mondays/Wednesday (room 104)"


def test_table_rows_stay_together_as_lines():
    grading = _by_heading(SYLLABUS_654)["Grading Algorithm"]
    assert grading.splitlines()[:3] == ["12.5% | Project", "17.5% | Labs", "30% | Assignments"]


def test_a_paragraph_that_only_starts_bold_is_body_text():
    grading = _by_heading(SYLLABUS_654)["Grading Algorithm"]
    assert grading.splitlines()[-1] == "Late Work Penalty: late work within a grace period is accepted for some labs."


def test_list_items_become_lines():
    assert _by_heading(SYLLABUS_654)["Brief List of Topics"] == "- Testing Basics\n- Unit Testing"


def test_headings_inside_table_cells_do_not_split_the_table():
    sections = _by_heading(SYLLABUS_658)
    assert list(sections) == ["Grading Rubric", "Units"]
    assert sections["Grading Rubric"].splitlines() == [
        "Your grade is determined along two dimensions.",
        "Component | Weight (%)",
        "Exam | 20",
        "Jama Lab | 5",
    ]


def test_text_before_any_heading_has_no_heading():
    sections = ingestion.extract_html_sections("<p>Welcome to the course.</p><h2>Week 1</h2><p>Read chapter 1.</p>")
    assert sections == [
        {"heading": None, "text": "Welcome to the course."},
        {"heading": "Week 1", "text": "Read chapter 1."},
    ]


def test_inline_runs_inside_a_container_stay_one_line():
    sections = ingestion.extract_html_sections('<div>Submit on <a href="#">Vocareum</a> by Friday.<p>Late work loses 10%.</p></div>')
    assert sections[0]["text"] == "Submit on Vocareum by Friday.\nLate work loses 10%."


def test_extract_html_page_is_the_sections_joined():
    text = ingestion.extract_html_page(SYLLABUS_654)
    assert "Grading Algorithm\n12.5% | Project" in text
