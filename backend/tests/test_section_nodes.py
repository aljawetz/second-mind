"""indexing.sections_to_nodes — Canvas HTML sections -> chunks, one section
at a time, each starting with where it came from."""

import indexing


def _texts(sections, source="Syllabus"):
    return [n.text for n in indexing.sections_to_nodes(sections, source, "syllabus:1", "syllabus")]


def test_each_chunk_starts_with_its_heading_path():
    texts = _texts([{"heading": "Grading Algorithm", "text": "12.5% | Project\n30% | Assignments"}])
    assert texts == ["Syllabus › Grading Algorithm\n12.5% | Project\n30% | Assignments"]


def test_sections_never_share_a_chunk():
    texts = _texts(
        [
            {"heading": "Teaching Assistants", "text": "- Lan Luo, Thursdays 3-4pm"},
            {"heading": "Grading Algorithm", "text": "12.5% | Project"},
        ]
    )
    assert len(texts) == 2
    assert "Lan Luo" not in texts[1]


def test_text_before_any_heading_uses_the_title_alone():
    assert _texts([{"heading": None, "text": "Welcome!"}], source="Week 1 Overview") == ["Week 1 Overview\nWelcome!"]


def test_headings_with_no_text_join_the_next_section():
    texts = _texts(
        [
            {"heading": "Class Schedule", "text": ""},
            {"heading": "Monday and Wednesday 3:00PM - 4:50PM", "text": ""},
            {"heading": "Supplemental Materials", "text": "- Koskela, Effective Unit Testing"},
        ]
    )
    assert texts == [
        "Syllabus › Supplemental Materials\nClass Schedule\nMonday and Wednesday 3:00PM - 4:50PM\n- Koskela, Effective Unit Testing"
    ]


def test_trailing_headings_with_no_text_are_kept():
    assert _texts([{"heading": "Units", "text": ""}]) == ["Syllabus\nUnits"]


def test_long_sections_split_under_the_embedding_window():
    long_text = "\n".join(f"Week {i} | Topic number {i} with a longer description of what is covered" for i in range(200))
    nodes = indexing.sections_to_nodes([{"heading": "Course Calendar", "text": long_text}], "Syllabus", "syllabus:1", "syllabus")
    assert len(nodes) > 1
    assert all(n.text.startswith("Syllabus › Course Calendar\n") for n in nodes)
    assert all(len(indexing._tokenize(n.text)) <= 512 for n in nodes)
    assert all(n.metadata["item_type"] == "syllabus" and n.metadata["page"] is None for n in nodes)
