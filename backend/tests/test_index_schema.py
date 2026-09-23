"""Course tables hold every material type in any order — TABLE_SCHEMA
(indexing.py).

Guards the real failure where LanceDB inferred column types from a table's
first batch: a lecture-first course rejected every PDF ("cannot cast field
'page' from Int64 to Null"), a PDF-first course rejected transcripts and
pptx slides. Needs models/bge-small-en-v1.5-onnx/ (real embeddings).
"""

from pathlib import Path

import lancedb
import pytest

import indexing

pytestmark = pytest.mark.skipif(
    not (Path(__file__).parent.parent / "models").exists(),
    reason="run scripts/convert_embedding_model.py first",
)

TABLE = "course_1"


def _transcript():
    segments = [{"start": 65.0, "end": 70.0, "text": "Today we cover regression testing and flaky tests."}]
    return indexing.transcript_to_nodes(segments, "Class 1", "session-1")


def _pdf():
    return indexing.pages_to_nodes([{"page": 3, "text": "Boundary value analysis picks inputs at the edges."}], "BVA.pdf", "file:10")


def _slides():
    return indexing.slides_to_nodes([{"slide": 2, "text": "The test pyramid: many unit tests, few UI tests."}], "deck.pptx", "file:11")


def _notes():
    return indexing.notes_to_nodes("My notes: ask about mutation testing.", "Class 1", "session-1")


def _anchors(db_path: Path) -> dict[str, tuple]:
    df = lancedb.connect(str(db_path)).open_table(TABLE).to_pandas()
    return {m["item_type"] + ":" + m["source"]: (m["page"], m["slide"], m["timestamp"]) for m in df["metadata"]}



@pytest.mark.parametrize(
    "order",
    [
        ["transcript", "pdf", "slides", "notes"],  # recorded a lecture before the first sync
        ["pdf", "slides", "transcript", "notes"],  # synced first, recorded later
    ],
)
def test_any_material_order_indexes_into_one_course(tmp_path, order):
    makers = {"transcript": _transcript, "pdf": _pdf, "slides": _slides, "notes": _notes}
    for kind in order:
        indexing.add_nodes(makers[kind](), tmp_path, TABLE)

    assert _anchors(tmp_path) == {
        "transcript:Class 1": (None, None, "1:05"),
        "file:BVA.pdf": (3, None, None),
        "file:deck.pptx": (None, 2, None),
        "notes:Class 1": (None, None, None),
    }
    assert lancedb.connect(str(tmp_path)).open_table(TABLE).schema == indexing.TABLE_SCHEMA

