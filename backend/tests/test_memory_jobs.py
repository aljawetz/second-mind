"""memory_jobs.py — feeds saved chats (conversations.py) to agent memory
(design spec §5.1): one turn at a time, dated when it was asked, progress
saved after each, and nothing kept from a chat deleted meanwhile."""

import json
import re
import zlib
from datetime import datetime, timezone

import numpy as np
import pytest

import conversations
import memory_jobs
from embeddings import MODEL_DIR
from memory import MemoryService

COURSE = 55710
CID = "c-000000000001"


def embed(text):
    v = [0.0] * 64
    for word in re.findall(r"\w+", text.lower()):
        v[zlib.crc32(word.encode()) % 64] += 1.0
    return v


class ScriptedLLM:
    def __init__(self, *replies, before_each=None):
        self._replies = list(replies)
        self._before_each = before_each
        self.calls = []

    def complete_json(self, messages):
        self.calls.append(messages[-1]["content"])
        if self._before_each:
            self._before_each()
        reply = self._replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def _extraction(text, summary):
    memory = {"kind": "fact", "text": text, "importance": 3, "event_time": None, "entities": [], "task_ref_hint": None}
    return {"memories": [memory], "summary": summary}


def _save(tmp_path, question, asked_at, cid=CID, course=COURSE):
    turn = {"question": question, "answer": "Noted.", "citations": [], "grounded": False, "asked_at": asked_at}
    conversations.append_turn(tmp_path, course, cid, turn)


@pytest.fixture
def service_with(tmp_path):
    opened = []

    def make(llm):
        svc = MemoryService(tmp_path, COURSE, llm=llm, embed=embed, now=lambda: datetime(2026, 9, 30, tzinfo=timezone.utc))
        opened.append(svc)
        return svc

    yield make
    for svc in opened:
        svc.close()


def test_unread_turns_are_read_one_at_a_time_and_dated_when_asked(tmp_path, service_with):
    _save(tmp_path, "I'm on team 4.", "2026-09-21T18:00:00Z")
    _save(tmp_path, "Please use Java.", "2026-09-22T09:30:00Z")
    llm = ScriptedLLM(_extraction("The student is on team 4.", "S1"), _extraction("The student wants Java.", "S2"))
    svc = service_with(llm)

    assert memory_jobs.observe_conversation(tmp_path, COURSE, CID, svc) == 2

    assert "I'm on team 4." in llm.calls[0] and "Please use Java." not in llm.calls[0]
    assert "Summary of the conversation so far: S1" in llm.calls[1]
    c = conversations.get_conversation(tmp_path, COURSE, CID)
    assert (c["memory_processed_upto"], c["summary"]) == (2, "S2")
    by_text = {m.text: m for m in svc.list()}
    assert by_text["The student is on team 4."].provenance == [(CID, 0)]
    assert by_text["The student is on team 4."].created_at == datetime(2026, 9, 21, 18, 0, tzinfo=timezone.utc)
    assert by_text["The student wants Java."].provenance == [(CID, 1)]


def test_turns_already_read_are_not_read_again(tmp_path, service_with):
    _save(tmp_path, "I'm on team 4.", "2026-09-21T18:00:00Z")
    _save(tmp_path, "Please use Java.", "2026-09-22T09:30:00Z")
    conversations.set_memory_progress(tmp_path, COURSE, CID, processed_upto=1, summary="S1")
    llm = ScriptedLLM(_extraction("The student wants Java.", "S2"))

    assert memory_jobs.observe_conversation(tmp_path, COURSE, CID, service_with(llm)) == 1
    assert len(llm.calls) == 1 and "Please use Java." in llm.calls[0]


def test_a_failed_turn_keeps_the_progress_made_before_it(tmp_path, service_with):
    _save(tmp_path, "I'm on team 4.", "2026-09-21T18:00:00Z")
    _save(tmp_path, "Please use Java.", "2026-09-22T09:30:00Z")
    llm = ScriptedLLM(_extraction("The student is on team 4.", "S1"), ConnectionError("model unreachable"))

    with pytest.raises(ConnectionError):
        memory_jobs.observe_conversation(tmp_path, COURSE, CID, service_with(llm))

    c = conversations.get_conversation(tmp_path, COURSE, CID)
    assert (c["memory_processed_upto"], c["summary"]) == (1, "S1")  # the second turn is retried later


def test_a_chat_deleted_while_being_read_leaves_no_memories(tmp_path, service_with):
    # The student can delete a chat while its job runs: the delete's cascade
    # has already happened, so the job must clean up after itself.
    _save(tmp_path, "I'm auditing the course.", "2026-09-21T18:00:00Z")
    llm = ScriptedLLM(
        _extraction("The student is auditing the course.", "S1"),
        before_each=lambda: conversations.delete_conversation(tmp_path, COURSE, CID),
    )
    svc = service_with(llm)

    memory_jobs.observe_conversation(tmp_path, COURSE, CID, svc)

    assert svc.list(include_inactive=True) == []
    assert not conversations.exists(tmp_path, COURSE, CID)


def test_a_missing_chat_reads_nothing(tmp_path, service_with):
    llm = ScriptedLLM()

    assert memory_jobs.observe_conversation(tmp_path, COURSE, "c-000000000009", service_with(llm)) == 0
    assert llm.calls == []


def test_a_blocked_turn_is_not_re_extracted(tmp_path, service_with):
    _save(tmp_path, "I'm auditing the course.", "2026-09-21T18:00:00Z")
    llm = ScriptedLLM(_extraction("The student is auditing the course.", "S1"))
    svc = service_with(llm)
    svc._store.block_forget_turn(CID, 0)

    assert memory_jobs.observe_conversation(tmp_path, COURSE, CID, svc) == 1

    assert svc.list() == []
    assert llm.calls == []


def test_a_summary_cleared_by_forget_is_not_written_back(tmp_path, service_with):
    _save(tmp_path, "I'm on team 4.", "2026-09-21T18:00:00Z")
    _save(tmp_path, "Please use Java.", "2026-09-22T09:30:00Z")
    conversations.set_memory_progress(tmp_path, COURSE, CID, processed_upto=1, summary="S1")
    llm = ScriptedLLM(
        _extraction("The student wants Java.", "S2"),
        before_each=lambda: conversations.set_memory_progress(tmp_path, COURSE, CID, processed_upto=1, summary=""),
    )

    memory_jobs.observe_conversation(tmp_path, COURSE, CID, service_with(llm))

    assert conversations.get_conversation(tmp_path, COURSE, CID)["summary"] == ""


def test_pending_lists_unread_chats_across_the_selected_courses(tmp_path):
    _save(tmp_path, "q", "2026-09-21T18:00:00Z", cid="c-000000000001")
    _save(tmp_path, "q", "2026-09-21T18:00:00Z", cid="c-000000000002")
    conversations.set_memory_progress(tmp_path, COURSE, "c-000000000002", processed_upto=1, summary="")
    conversations.set_turns_indexed(tmp_path, COURSE, "c-000000000002", 1)  # read and indexed: nothing left to do
    _save(tmp_path, "q", "2026-09-21T18:00:00Z", cid="c-000000000003", course=55016)
    _save(tmp_path, "q", "2026-09-21T18:00:00Z", cid="c-000000000004", course=11111)  # not selected

    assert memory_jobs.pending(tmp_path, [COURSE, 55016]) == [(COURSE, "c-000000000001"), (55016, "c-000000000003")]


@pytest.mark.skipif(not MODEL_DIR.exists(), reason="run scripts/convert_embedding_model.py first")
def test_the_shared_embedder_gives_normalized_bge_vectors():
    a = np.array(memory_jobs.embed("The student is on team 4."))
    b = np.array(memory_jobs.embed("Which team am I on?"))
    c = np.array(memory_jobs.embed("How do I bake sourdough bread?"))

    assert a.shape == (384,)
    assert np.linalg.norm(a) == pytest.approx(1.0, abs=1e-5)
    assert a @ b > a @ c


# --- past-chat index (docs/specs/2026-11-10-past-chat-search-design.md §3) -----


def _indexed(svc):
    return [(t.conversation_id, t.turn_index, t.question) for t in svc._store.list_turns()]


def test_reading_a_chat_also_makes_its_turns_searchable_from_other_chats(tmp_path, service_with):
    _save(tmp_path, "I'm on team 4.", "2026-09-21T18:00:00Z")
    svc = service_with(ScriptedLLM(_extraction("The student is on team 4.", "S1")))

    memory_jobs.observe_conversation(tmp_path, COURSE, CID, svc)

    [turn] = svc.search_past_chats("which team am I on?")
    assert (turn.conversation_id, turn.turn_index, turn.question, turn.answer) == (CID, 0, "I'm on team 4.", "Noted.")
    assert turn.title == "I'm on team 4." and turn.at == datetime(2026, 9, 21, 18, 0, tzinfo=timezone.utc)
    assert conversations.get_conversation(tmp_path, COURSE, CID)["turns_indexed_upto"] == 1


def test_turns_are_indexed_even_when_the_model_call_fails(tmp_path, service_with):
    _save(tmp_path, "I'm on team 4.", "2026-09-21T18:00:00Z")
    svc = service_with(ScriptedLLM(RuntimeError("no OpenAI key stored")))

    with pytest.raises(RuntimeError):
        memory_jobs.observe_conversation(tmp_path, COURSE, CID, svc)

    assert _indexed(svc) == [(CID, 0, "I'm on team 4.")]
    assert conversations.get_conversation(tmp_path, COURSE, CID)["turns_indexed_upto"] == 1


def test_turns_already_indexed_are_not_indexed_again(tmp_path, service_with):
    _save(tmp_path, "I'm on team 4.", "2026-09-21T18:00:00Z")
    svc = service_with(ScriptedLLM(_extraction("The student is on team 4.", "S1")))
    memory_jobs.observe_conversation(tmp_path, COURSE, CID, svc)
    svc._store.delete_turns(CID)

    memory_jobs.observe_conversation(tmp_path, COURSE, CID, svc)

    assert _indexed(svc) == []


def test_a_chat_saved_before_the_index_existed_is_caught_up_without_the_model(tmp_path, service_with):
    _save(tmp_path, "I'm on team 4.", "2026-09-21T18:00:00Z")
    conversations.set_memory_progress(tmp_path, COURSE, CID, processed_upto=1, summary="S1")
    # What an old file looks like: memory has read it, the counter isn't there.
    path = tmp_path / "courses" / str(COURSE) / "conversations" / f"{CID}.json"
    data = json.loads(path.read_text())
    data.pop("turns_indexed_upto", None)
    path.write_text(json.dumps(data))
    llm = ScriptedLLM()
    svc = service_with(llm)

    assert memory_jobs.pending(tmp_path, [COURSE]) == [(COURSE, CID)]
    assert memory_jobs.observe_conversation(tmp_path, COURSE, CID, svc) == 0

    assert _indexed(svc) == [(CID, 0, "I'm on team 4.")]
    assert llm.calls == []
    assert memory_jobs.pending(tmp_path, [COURSE]) == []


def test_a_turn_about_grades_is_passed_over_and_not_tried_again(tmp_path, service_with):
    _save(tmp_path, "I got a 72 on the midterm.", "2026-09-21T18:00:00Z")
    svc = service_with(ScriptedLLM({"memories": [], "summary": ""}))

    memory_jobs.observe_conversation(tmp_path, COURSE, CID, svc)

    assert _indexed(svc) == []
    assert conversations.get_conversation(tmp_path, COURSE, CID)["turns_indexed_upto"] == 1


def test_forgetting_a_deleted_chat_removes_its_turns_from_the_index(tmp_path, service_with):
    _save(tmp_path, "I'm on team 4.", "2026-09-21T18:00:00Z")
    _save(tmp_path, "Use Java please.", "2026-09-22T09:30:00Z", cid="c-000000000002")
    svc = service_with(ScriptedLLM(_extraction("The student is on team 4.", "S1"), _extraction("The student wants Java.", "S2")))
    memory_jobs.observe_conversation(tmp_path, COURSE, CID, svc)
    memory_jobs.observe_conversation(tmp_path, COURSE, "c-000000000002", svc)

    svc.forget_conversation(CID)

    assert _indexed(svc) == [("c-000000000002", 0, "Use Java please.")]
