"""conversations.py — saved course chats, one JSON file per conversation
(docs/superpowers/plans/2026-09-23-conversation-history.md, Task 1), plus
the two fields agent memory keeps in them: how far memory has read the
chat, and its running summary (agent memory design spec §5.1, §5.6)."""

import re
import threading

import pytest

import conversations

COURSE = 55710


def _turn(question="What does the rubric say about test coverage?", asked_at="2026-09-23T14:05:12Z", answer="20 points. [1]"):
    return {
        "question": question,
        "answer": answer,
        "citations": [{"source_type": "file", "label": "Rubric.pdf · p.2", "item_id": "file:123"}],
        "grounded": True,
        "asked_at": asked_at,
    }


def test_ids_are_short_and_safe_in_a_url():
    ids = {conversations.new_conversation_id() for _ in range(50)}

    assert len(ids) == 50
    assert all(re.fullmatch(r"c-[0-9a-f]{12}", cid) for cid in ids)


def test_the_first_turn_creates_the_conversation_titled_by_its_question(tmp_path):
    cid = conversations.new_conversation_id()
    assert not conversations.exists(tmp_path, COURSE, cid)

    conversations.append_turn(tmp_path, COURSE, cid, _turn())

    assert conversations.exists(tmp_path, COURSE, cid)
    c = conversations.get_conversation(tmp_path, COURSE, cid)
    assert c["conversation_id"] == cid
    assert c["title"] == "What does the rubric say about test coverage?"
    assert c["created_at"] == c["updated_at"] == "2026-09-23T14:05:12Z"
    assert c["turns"] == [_turn()]
    assert (tmp_path / "courses" / str(COURSE) / "conversations" / f"{cid}.json").exists()


def test_a_long_first_question_is_cut_to_a_60_character_title(tmp_path):
    question = "  Can you explain,   in detail, " + "why mocks differ from stubs " * 5
    conversations.append_turn(tmp_path, COURSE, "c-000000000001", _turn(question=question))

    title = conversations.get_conversation(tmp_path, COURSE, "c-000000000001")["title"]
    assert len(title) == 60
    assert title.startswith("Can you explain, in detail, why mocks differ")


def test_later_turns_are_appended_and_move_updated_at(tmp_path):
    cid = "c-000000000001"
    conversations.append_turn(tmp_path, COURSE, cid, _turn())
    conversations.append_turn(tmp_path, COURSE, cid, _turn(question="And the final?", asked_at="2026-09-23T14:09:40Z"))

    c = conversations.get_conversation(tmp_path, COURSE, cid)
    assert [t["question"] for t in c["turns"]] == ["What does the rubric say about test coverage?", "And the final?"]
    assert (c["created_at"], c["updated_at"]) == ("2026-09-23T14:05:12Z", "2026-09-23T14:09:40Z")
    assert c["title"] == "What does the rubric say about test coverage?"


def test_the_list_is_per_course_newest_first_and_summaries_only(tmp_path):
    conversations.append_turn(tmp_path, COURSE, "c-000000000001", _turn(asked_at="2026-09-20T10:00:00Z"))
    conversations.append_turn(tmp_path, COURSE, "c-000000000002", _turn(question="Q2", asked_at="2026-09-22T10:00:00Z"))
    conversations.append_turn(tmp_path, COURSE, "c-000000000001", _turn(question="Q1b", asked_at="2026-09-23T10:00:00Z"))
    conversations.append_turn(tmp_path, 55016, "c-000000000003", _turn(asked_at="2026-09-24T10:00:00Z"))

    assert conversations.list_conversations(tmp_path, COURSE) == [
        {"conversation_id": "c-000000000001", "title": "What does the rubric say about test coverage?", "updated_at": "2026-09-23T10:00:00Z", "turn_count": 2},
        {"conversation_id": "c-000000000002", "title": "Q2", "updated_at": "2026-09-22T10:00:00Z", "turn_count": 1},
    ]


def test_a_course_with_no_conversations_lists_none(tmp_path):
    assert conversations.list_conversations(tmp_path, COURSE) == []


def test_a_missing_conversation_reads_as_none_and_cannot_be_deleted(tmp_path):
    assert conversations.get_conversation(tmp_path, COURSE, "c-000000000009") is None
    with pytest.raises(KeyError):
        conversations.delete_conversation(tmp_path, COURSE, "c-000000000009")


def test_deleting_removes_the_file(tmp_path):
    conversations.append_turn(tmp_path, COURSE, "c-000000000001", _turn())

    conversations.delete_conversation(tmp_path, COURSE, "c-000000000001")

    assert not conversations.exists(tmp_path, COURSE, "c-000000000001")
    assert conversations.list_conversations(tmp_path, COURSE) == []


def test_two_requests_appending_at_once_both_land(tmp_path):
    # ThreadingHTTPServer can run two /ask requests for one conversation.
    cid = "c-000000000001"
    threads = [
        threading.Thread(target=conversations.append_turn, args=(tmp_path, COURSE, cid, _turn(question=f"Q{i}")))
        for i in range(20)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    turns = conversations.get_conversation(tmp_path, COURSE, cid)["turns"]
    assert sorted(t["question"] for t in turns) == sorted(f"Q{i}" for i in range(20))
    assert [p.name for p in (tmp_path / "courses" / str(COURSE) / "conversations").iterdir()] == [f"{cid}.json"]


def test_a_new_conversation_has_nothing_read_by_memory_yet(tmp_path):
    conversations.append_turn(tmp_path, COURSE, "c-000000000001", _turn())

    c = conversations.get_conversation(tmp_path, COURSE, "c-000000000001")
    assert (c["memory_processed_upto"], c["summary"]) == (0, "")
    assert conversations.pending_memory(tmp_path, COURSE) == ["c-000000000001"]


def test_memory_progress_is_saved_without_touching_the_turns(tmp_path):
    cid = "c-000000000001"
    conversations.append_turn(tmp_path, COURSE, cid, _turn())
    conversations.append_turn(tmp_path, COURSE, cid, _turn(question="Q2"))

    conversations.set_memory_progress(tmp_path, COURSE, cid, processed_upto=1, summary="Asked about the rubric.")

    c = conversations.get_conversation(tmp_path, COURSE, cid)
    assert (c["memory_processed_upto"], c["summary"]) == (1, "Asked about the rubric.")
    assert len(c["turns"]) == 2
    assert conversations.pending_memory(tmp_path, COURSE) == [cid]

    conversations.set_memory_progress(tmp_path, COURSE, cid, processed_upto=2, summary="Rubric, then Q2.")
    assert conversations.pending_memory(tmp_path, COURSE) == []


def test_memory_progress_on_a_deleted_conversation_is_ignored(tmp_path):
    # The student can delete a chat while the background worker is still
    # reading it; the worker must not bring the file back.
    conversations.set_memory_progress(tmp_path, COURSE, "c-000000000009", processed_upto=1, summary="x")

    assert not conversations.exists(tmp_path, COURSE, "c-000000000009")
