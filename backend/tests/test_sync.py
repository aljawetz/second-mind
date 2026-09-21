"""implementation-plan.md Step 7. Diff logic tested against simulated
Canvas listings (design spec §5.5's own test scope — mocked, not live).
The delete_ref_doc integration test caught a real upstream bug: verified
against real requirements below.
"""

import tempfile
from pathlib import Path

import pytest

import indexing
import sync


@pytest.fixture
def conn(tmp_path):
    return sync.open_manifest(tmp_path / "manifest.db")


def test_diff_new_item(conn):
    result = sync.diff(conn, "page", [{"id": "1", "updated_at": "2026-01-01"}])
    assert result == {"new": ["1"], "changed": [], "deleted": [], "unchanged": []}


def test_diff_unchanged_item(conn):
    sync.mark_synced(conn, "1", "page", "Test Page", "2026-01-01", "hash-a")
    result = sync.diff(conn, "page", [{"id": "1", "updated_at": "2026-01-01"}])
    assert result == {"new": [], "changed": [], "deleted": [], "unchanged": ["1"]}


def test_diff_changed_item(conn):
    sync.mark_synced(conn, "1", "page", "Test Page", "2026-01-01", "hash-a")
    result = sync.diff(conn, "page", [{"id": "1", "updated_at": "2026-01-02"}])
    assert result == {"new": [], "changed": ["1"], "deleted": [], "unchanged": []}


def test_diff_deleted_item(conn):
    sync.mark_synced(conn, "1", "page", "Test Page", "2026-01-01", "hash-a")
    result = sync.diff(conn, "page", [])
    assert result == {"new": [], "changed": [], "deleted": ["1"], "unchanged": []}


def test_diff_item_types_are_independent(conn):
    """A page and a file can share the same canvas_item_id namespace-wise
    (schema §4's PRIMARY KEY is (canvas_item_id, item_type)) without
    colliding."""
    sync.mark_synced(conn, "1", "page", "Test Page", "2026-01-01", "hash-a")
    result = sync.diff(conn, "file", [{"id": "1", "updated_at": "2026-01-01"}])
    assert result["new"] == ["1"]  # "1" is new for item_type "file", unrelated to the page row


@pytest.mark.skipif(
    not (Path(__file__).parent.parent / "models").exists(),
    reason="run scripts/convert_embedding_model.py first",
)
def test_changed_and_deleted_items_end_to_end(tmp_path):
    """The plan's actual test: simulate a changed item and a deleted item,
    confirm both the manifest and the LanceDB table end up correct —
    specifically that delete_ref_doc removed exactly the right chunks."""
    conn = sync.open_manifest(tmp_path / "manifest.db")

    with tempfile.TemporaryDirectory() as db_dir:
        db_path = Path(db_dir)

        # Initial sync: two items already indexed and recorded.
        old_a_pages = [{"page": 1, "text": "Original content about topic A. " * 20}]
        old_b_pages = [{"page": 1, "text": "Content about topic B that will be deleted. " * 20}]
        nodes = indexing.pages_to_nodes(old_a_pages, "doc_a", "item_a")
        nodes += indexing.pages_to_nodes(old_b_pages, "doc_b", "item_b")
        index = indexing.build_index(nodes, db_path, "course")
        sync.mark_synced(conn, "item_a", "page", "Doc A", "2026-01-01", sync.content_hash(old_a_pages[0]["text"]))
        sync.mark_synced(conn, "item_b", "page", "Doc B", "2026-01-01", sync.content_hash(old_b_pages[0]["text"]))

        table = index.vector_store.table
        assert table.count_rows() == 2

        # New sync: item_a's remote updated_at moved forward (changed),
        # item_b is gone from the remote listing entirely (deleted).
        result = sync.diff(conn, "page", [{"id": "item_a", "updated_at": "2026-01-02"}])
        assert result == {"new": [], "changed": ["item_a"], "deleted": ["item_b"], "unchanged": []}

        # Process "changed": re-extract (simulated), hash differs -> replace.
        new_a_pages = [{"page": 1, "text": "Updated content about topic A, now different. " * 20}]
        new_hash = sync.content_hash(new_a_pages[0]["text"])
        assert new_hash != sync.get_content_hash(conn, "item_a", "page")
        index.delete_ref_doc("item_a", delete_from_docstore=True)
        for node in indexing.pages_to_nodes(new_a_pages, "doc_a", "item_a"):
            index.insert_nodes([node])
        sync.mark_synced(conn, "item_a", "page", "Doc A", "2026-01-02", new_hash)

        # Process "deleted": remove chunks, drop the manifest row.
        index.delete_ref_doc("item_b", delete_from_docstore=True)
        sync.forget(conn, "item_b", "page")

        # LanceDB table: item_b's row is gone entirely, item_a has exactly
        # one row with the *new* content, not the old one duplicated.
        df = table.to_pandas()
        assert set(df["doc_id"]) == {"item_a"}
        assert len(df) == 1
        assert "Updated content" in df.iloc[0]["text"]
        assert "Original content" not in df.iloc[0]["text"]

        # manifest.db: item_b's row is gone, item_a reflects the new sync.
        remaining = conn.execute("SELECT canvas_item_id FROM manifest").fetchall()
        assert remaining == [("item_a",)]
        assert sync.get_content_hash(conn, "item_a", "page") == new_hash
