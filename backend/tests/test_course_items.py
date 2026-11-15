"""course_items.py — the course outline behind chat's list_course_items tool
(RAG gaps plan task 8). Built from the Canvas module structure the sync
already fetches; no network here."""

import sqlite3

import course_items
import sync

STRUCTURE = [
    {
        "name": "Week 1: Introduction",
        "items": [
            {"type": "Page", "title": "Welcome"},
            {"type": "SubHeader", "title": "Readings"},
            {"type": "File", "title": "Koskela Ch1-2 (M)"},
            {"type": "ExternalUrl", "title": "TDD primer", "external_url": "https://example.org/tdd"},
        ],
    },
    {
        "name": "Week 3: Elicitation",
        "items": [
            {"type": "File", "title": "03 Interviews.pdf"},
            {"type": "Assignment", "title": "A1 - Interview plan"},
            {"type": "Quiz", "title": "Quiz 3"},
        ],
    },
    {"name": "Week 30 extras", "items": [{"type": "Discussion", "title": "Intros"}]},
]


def _rows():
    return course_items.outline_rows(STRUCTURE)


def test_outline_rows_flatten_modules_with_sub_headers_as_sections():
    rows = _rows()
    assert [(r["module"], r["section"], r["title"], r["item_type"]) for r in rows] == [
        ("Week 1: Introduction", "", "Welcome", "page"),
        ("Week 1: Introduction", "Readings", "Koskela Ch1-2 (M)", "file"),
        ("Week 1: Introduction", "Readings", "TDD primer", "link"),
        ("Week 3: Elicitation", "", "03 Interviews.pdf", "file"),
        ("Week 3: Elicitation", "", "A1 - Interview plan", "assignment"),
        ("Week 3: Elicitation", "", "Quiz 3", "quiz"),
        ("Week 30 extras", "", "Intros", "discussion"),
    ]
    assert rows[2]["url"] == "https://example.org/tdd"
    assert rows[0]["url"] == ""


def test_outline_rows_skip_items_without_a_title_and_tidy_whitespace():
    rows = course_items.outline_rows(
        [{"name": "  Unit  1 ", "items": [{"type": "File", "title": "  L1   - TDD Lab "}, {"type": "File"}]}, {"items": []}]
    )
    assert [(r["module"], r["title"]) for r in rows] == [("Unit 1", "L1 - TDD Lab")]


def test_saved_outline_is_replaced_on_the_next_save(tmp_path):
    conn = sync.open_manifest(tmp_path / "manifest.db")
    course_items.save_outline(conn, _rows())
    course_items.save_outline(conn, _rows()[:2])
    assert [r["title"] for r in course_items.load_outline(conn)] == ["Welcome", "Koskela Ch1-2 (M)"]


def test_no_filter_lists_everything_grouped_by_module_and_section():
    text = course_items.format_listing(_rows())
    assert "7 items" in text
    assert text.index("Week 1: Introduction") < text.index("Readings") < text.index("Koskela Ch1-2 (M) (file)")
    assert "TDD primer (link: https://example.org/tdd)" in text
    assert "Week 3: Elicitation" in text


def test_topic_matches_whole_words_in_the_module_name():
    text = course_items.format_listing(_rows(), topic="week 3")
    assert "03 Interviews.pdf" in text and "Quiz 3" in text
    assert "Intros" not in text  # "Week 30" is not week 3
    assert "Welcome" not in text


def test_topic_matching_a_section_or_title_lists_just_those_items():
    by_section = course_items.format_listing(_rows(), topic="readings")
    assert "Koskela" in by_section and "TDD primer" in by_section and "Welcome" not in by_section
    by_title = course_items.format_listing(_rows(), topic="interview")
    assert "A1 - Interview plan" in by_title  # whole word, case-insensitive
    assert "03 Interviews.pdf" in by_title  # a plural "s" either way
    assert "Welcome" not in by_title


def test_types_filter_keeps_only_those_kinds():
    text = course_items.format_listing(_rows(), types=["file", "link"])
    assert "Koskela" in text and "TDD primer" in text and "03 Interviews.pdf" in text
    assert "Welcome" not in text and "Quiz 3" not in text


def test_no_match_says_so_and_names_the_modules():
    text = course_items.format_listing(_rows(), topic="week 9")
    assert "Nothing" in text
    assert "Week 1: Introduction; Week 3: Elicitation; Week 30 extras" in text


def test_a_long_listing_is_cut_and_says_how_many_were_left_out(monkeypatch):
    monkeypatch.setattr(course_items, "MAX_ITEMS", 3)
    text = course_items.format_listing(_rows())
    assert "Koskela" in text and "03 Interviews.pdf" not in text
    assert "4 more" in text


def test_list_for_course_reads_the_saved_outline(tmp_path):
    path = tmp_path / "courses" / "7" / "manifest.db"
    path.parent.mkdir(parents=True)
    conn = sync.open_manifest(path)
    course_items.save_outline(conn, _rows())
    conn.close()
    assert "Koskela" in course_items.list_for_course(tmp_path, 7, topic="week 1")


def test_list_for_course_falls_back_to_the_manifest_before_the_outline_is_saved(tmp_path):
    path = tmp_path / "courses" / "7" / "manifest.db"
    path.parent.mkdir(parents=True)
    conn = sync.open_manifest(path)
    conn.executemany(
        "INSERT INTO manifest VALUES (?, ?, ?, '', '', '')",
        [("file:1", "file", "Lecture 1.pdf"), ("page:intro", "page", "Intro"), ("syllabus:7", "syllabus", "Syllabus")],
    )
    conn.commit()
    conn.close()
    text = course_items.list_for_course(tmp_path, 7, types=["file"])
    assert "Lecture 1.pdf" in text and "Intro" not in text
    assert "not grouped by module" in text


def test_list_for_course_on_a_course_never_synced_creates_nothing(tmp_path):
    text = course_items.list_for_course(tmp_path, 7)
    assert "hasn't been synced" in text
    assert not (tmp_path / "courses").exists()


def test_reading_the_listing_never_writes_to_the_manifest(tmp_path):
    path = tmp_path / "courses" / "7" / "manifest.db"
    path.parent.mkdir(parents=True)
    sqlite3.connect(path).close()  # an old manifest with no tables at all
    assert "hasn't been synced" in course_items.list_for_course(tmp_path, 7)


def test_topic_words_may_be_spread_over_module_section_and_title():
    """The model asks for "sprint deliverables" when "Sprint" is in the item
    names and "Deliverables" in the module's (56350, listing eval)."""
    rows = course_items.outline_rows(
        [{"name": "Weekly Project Deliverables", "items": [{"type": "Assignment", "title": "Sprint 1 Deliverable"}, {"type": "Assignment", "title": "Democracy Day"}]}]
    )
    text = course_items.format_listing(rows, topic="sprint deliverables")
    assert "Sprint 1 Deliverable" in text and "Democracy Day" not in text
    assert "Sprint 1 Deliverable" in course_items.format_listing(rows, topic="Deliverables sprint")
