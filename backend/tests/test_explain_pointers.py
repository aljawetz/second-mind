"""explain.build_pointers with assignments in the index (course_sync.py
indexes their descriptions). The pointer query is the assignment's own
text, so without a filter its indexed copy ranks first — a pointer back to
the prompt the student is already reading. Needs the embedding model."""

from pathlib import Path

import pytest

import explain
import indexing

pytestmark = pytest.mark.skipif(
    not (Path(__file__).parent.parent / "models").exists(),
    reason="run scripts/convert_embedding_model.py first",
)

NAME = "Task 2: Stakeholder Interviews"
DESCRIPTION = (
    "Interview at least three stakeholders about how they currently plan study sessions. "
    "Record their goals and pain points, then summarize the interviews as affinity notes."
)


def test_pointers_lead_to_course_material_not_the_assignment_itself(tmp_path):
    nodes = indexing.pages_to_nodes(
        [{"page": None, "text": DESCRIPTION, "needs_fallback": False}], NAME, "assignment:2", item_type="assignment"
    )
    nodes += indexing.pages_to_nodes(
        [{"page": 4, "text": "Stakeholder interviews: ask about goals and pain points, then build affinity notes."}],
        "Lecture 3 - Elicitation.pdf",
        "file:30",
    )
    indexing.add_nodes(nodes, tmp_path, "course_1")

    pointers = explain.build_pointers(indexing.load_index(tmp_path, "course_1"), NAME, DESCRIPTION)

    assert all(p["source_type"] != "assignment" for p in pointers)
    assert [p["item_id"] for p in pointers] == ["file:30"]
