"""transcript_to_nodes / notes_to_nodes — implementation-plan.md Step 12.
Pure node-shape tests, no embedding model or index needed."""

from llama_index.core.schema import NodeRelationship

import indexing


def test_transcript_to_nodes_labels_by_timestamp():
    segments = [
        {"start": 0.0, "end": 4.0, "text": "Welcome to today's lecture."},
        {"start": 4.0, "end": 9.0, "text": "We'll cover dependency injection."},
    ]
    nodes = indexing.transcript_to_nodes(segments, "Class — Sep 17", "session-123")
    assert len(nodes) == 1
    node = nodes[0]
    assert node.metadata["item_type"] == "transcript"
    assert node.metadata["timestamp"] == "0:00"
    assert node.metadata["source"] == "Class — Sep 17"
    assert "dependency injection" in node.text
    assert node.relationships[NodeRelationship.SOURCE].node_id == "session-123"


def test_transcript_to_nodes_splits_long_transcript_into_multiple_timestamped_chunks():
    long_text = "Testing double strategies in depth. " * 200  # forces a buffer flush
    segments = [{"start": 0.0, "end": 5.0, "text": long_text}, {"start": 300.0, "end": 305.0, "text": "Second part."}]
    nodes = indexing.transcript_to_nodes(segments, "Class — Sep 17", "session-123")
    assert len(nodes) >= 2
    assert nodes[0].metadata["timestamp"] == "0:00"
    assert nodes[-1].metadata["timestamp"] == "5:00"


def test_transcript_to_nodes_empty_segments_returns_no_nodes():
    assert indexing.transcript_to_nodes([], "Class — Sep 17", "session-123") == []


def test_notes_to_nodes_blank_text_returns_no_nodes():
    assert indexing.notes_to_nodes("   ", "Class — Sep 17", "session-123") == []


def test_notes_to_nodes_real_text():
    nodes = indexing.notes_to_nodes("Remember: mocks vs stubs distinction.", "Class — Sep 17", "session-123")
    assert len(nodes) == 1
    assert nodes[0].metadata["item_type"] == "notes"
    assert nodes[0].relationships[NodeRelationship.SOURCE].node_id == "session-123"
