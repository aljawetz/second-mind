"""ingestion.extract_html_page — docs/superpowers/specs/2026-09-20-course-sync-phase1-design.md.
Plain inline HTML, no external fixtures needed (unlike test_ingestion.py's
real-course-material tests)."""

import ingestion


def test_strips_tags_and_keeps_text():
    html = "<h1>Week 1</h1><p>Read chapters 1-3 before class.</p>"
    text = ingestion.extract_html_page(html)
    assert "Week 1" in text
    assert "Read chapters 1-3 before class." in text
    assert "<h1>" not in text
    assert "<p>" not in text


def test_separates_block_elements_with_whitespace():
    """Real bug this guards against: naive tag-stripping with no separator
    would glue "Week 1" and "Overview" into "Week 1Overview" with no space
    between adjacent block elements."""
    html = "<h1>Week 1</h1><h2>Overview</h2>"
    text = ingestion.extract_html_page(html)
    assert "Week 1" in text
    assert "Overview" in text
    assert "Week 1Overview" not in text


def test_drops_script_and_style_content_entirely():
    html = "<p>Visible text.</p><script>var x = 1;</script><style>.a{color:red}</style>"
    text = ingestion.extract_html_page(html)
    assert "Visible text." in text
    assert "var x" not in text
    assert "color:red" not in text


def test_empty_body_returns_empty_string():
    assert ingestion.extract_html_page("") == ""
    assert ingestion.extract_html_page("<p></p>") == ""
