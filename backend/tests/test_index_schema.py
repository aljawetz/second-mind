"""Course tables hold every material type in any order — TABLE_SCHEMA and
repair_table_schema (indexing.py).

Guards the real failure where LanceDB inferred column types from a table's
first batch: a lecture-first course rejected every PDF ("cannot cast field
'page' from Int64 to Null"), a PDF-first course rejected transcripts and
pptx slides. Needs models/bge-small-en-v1.5-onnx/ (real embeddings).
"""

from pathlib import Path

import lancedb
import pyarrow as pa
import pytest
from llama_index.core import StorageContext, VectorStoreIndex
from llama_index.core.schema import TextNode
from llama_index.vector_stores.lancedb import LanceDBVectorStore

import indexing
from embeddings import OnnxBgeEmbedding

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


def _legacy_table(db_path: Path, nodes) -> None:
    """A table built the way it was before TABLE_SCHEMA: the unpatched
    llama-index store, which infers types from this first batch."""
    store = LanceDBVectorStore(uri=str(db_path), table_name=TABLE)
    VectorStoreIndex(
        nodes,
        storage_context=StorageContext.from_defaults(vector_store=store),
        embed_model=OnnxBgeEmbedding(),
        transformations=[indexing._splitter],
    )


def _metadata_type(db_path: Path) -> pa.StructType:
    return lancedb.connect(str(db_path)).open_table(TABLE).schema.field("metadata").type


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


def test_repairs_a_lecture_first_table_so_pdfs_index(tmp_path):
    _legacy_table(tmp_path, _transcript())
    assert _metadata_type(tmp_path).field("page").type == pa.null()  # the real broken state
    before = lancedb.connect(str(tmp_path)).open_table(TABLE).to_pandas()

    indexing.add_nodes(_pdf() + _slides(), tmp_path, TABLE)

    table = lancedb.connect(str(tmp_path)).open_table(TABLE)
    assert table.schema == indexing.TABLE_SCHEMA
    assert _anchors(tmp_path) == {
        "transcript:Class 1": (None, None, "1:05"),
        "file:BVA.pdf": (3, None, None),
        "file:deck.pptx": (None, 2, None),
    }
    # The existing transcript row survived as-is: same text, same vector —
    # repaired, not re-embedded.
    after = table.to_pandas().set_index("id")
    row = before.iloc[0]
    assert after.loc[row["id"], "text"] == row["text"]
    assert list(after.loc[row["id"], "vector"]) == list(row["vector"])
    # FTS survives the overwrite (HybridRetriever depends on it).
    assert len(table.search("regression", query_type="fts").limit(1).to_list()) == 1


def test_repairs_a_pdf_first_table_so_lectures_and_slides_index(tmp_path):
    _legacy_table(tmp_path, _pdf())
    assert _metadata_type(tmp_path).field("timestamp").type == pa.null()

    indexing.add_nodes(_transcript(), tmp_path, TABLE)
    indexing.add_nodes(_slides(), tmp_path, TABLE)

    assert set(_anchors(tmp_path)) == {"file:BVA.pdf", "transcript:Class 1", "file:deck.pptx"}


def test_repairs_a_table_missing_metadata_fields(tmp_path):
    # Tables from before _metadata() carried every key had no slide/timestamp
    # columns at all, not just null-typed ones.
    old_node = TextNode(text="Old page content about test oracles.", metadata={"source": "old.pdf", "item_type": "file", "page": 1})
    _legacy_table(tmp_path, [old_node])
    assert _metadata_type(tmp_path).get_field_index("timestamp") == -1

    indexing.add_nodes(_transcript(), tmp_path, TABLE)

    assert _anchors(tmp_path) == {"file:old.pdf": (1, None, None), "transcript:Class 1": (None, None, "1:05")}


def test_repair_leaves_a_correct_table_alone(tmp_path):
    indexing.add_nodes(_pdf(), tmp_path, TABLE)
    version = lancedb.connect(str(tmp_path)).open_table(TABLE).version

    assert indexing.repair_table_schema(tmp_path, TABLE) is False
    assert lancedb.connect(str(tmp_path)).open_table(TABLE).version == version
