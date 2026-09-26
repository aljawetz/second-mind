"""main.py's /ask with saved chats and agent memory, and the conversation
and memory endpoints (conversation-history plan Tasks 2-3; agent memory
design spec §8, §9). The real HTTP handler, in-process on a free port, with
a temporary ~/.secondmind, no course index, and a scripted model standing
in for OpenAI. No network, no key."""

import http.client
import json
import re
import threading
import zlib
from types import SimpleNamespace

import pytest
from llama_index.vector_stores.lancedb.base import TableNotFoundError

import config
import conversations
import indexing
import llm
import main
import memory_jobs
from llm import TurnEnd

COURSE = 55710


def embed(text):
    v = [0.0] * 64
    for word in re.findall(r"\w+", text.lower()):
        v[zlib.crc32(word.encode()) % 64] += 1.0
    return v


def _extraction(text):
    memory = {"kind": "fact", "text": text, "importance": 4, "event_time": None, "entities": [], "task_ref_hint": None}
    return {"memories": [memory], "summary": "s"}


class FakeModel:
    """Stands in for llm.OpenAIProvider: scripted streamed replies for /ask,
    scripted JSON replies for the memory worker."""

    def __init__(self):
        self.chat_replies, self.json_replies = [], []
        self.chat_calls, self.json_calls = [], []

    def stream_chat(self, messages, tools, require_tool=False):
        self.chat_calls.append([dict(m) for m in messages])
        for piece in self.chat_replies.pop(0):
            if isinstance(piece, Exception):
                raise piece
            yield piece
        yield TurnEnd()

    def complete_json(self, messages):
        self.json_calls.append(messages)
        reply = self.json_replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


@pytest.fixture
def app(tmp_path, monkeypatch):
    config.write_config(tmp_path, {"selected_courses": [COURSE]})
    monkeypatch.setattr(main, "SM_HOME", tmp_path)

    def no_index(*args, **kwargs):
        raise TableNotFoundError("course not indexed")

    monkeypatch.setattr(indexing, "load_index", no_index)
    monkeypatch.setattr(memory_jobs, "embed", embed)
    model = FakeModel()
    monkeypatch.setattr(llm, "OpenAIProvider", lambda *args, **kwargs: model)

    server = main.ThreadingHTTPServer(("127.0.0.1", 0), main.Handler)
    threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
    yield SimpleNamespace(port=server.server_address[1], model=model, home=tmp_path)
    # Before monkeypatch puts SM_HOME back: no job may reach the real one.
    assert main.MEMORY_WORKER.wait_idle(10)
    server.shutdown()
    server.server_close()


def _request(app, method, path, body=None):
    conn = http.client.HTTPConnection("127.0.0.1", app.port, timeout=10)
    conn.request(method, path, json.dumps(body) if body is not None else None)
    res = conn.getresponse()
    raw = res.read().decode()
    conn.close()
    return res.status, raw


def _json(app, method, path):
    status, raw = _request(app, method, path)
    return status, json.loads(raw)


def _ask(app, question, **body):
    status, raw = _request(app, "POST", f"/courses/{COURSE}/ask", {"question": question, "course_name": "Test", **body})
    if status != 200:
        return status, json.loads(raw)
    return status, [json.loads(line) for line in raw.splitlines() if line.strip()]


def _final(events):
    return next(e for e in events if "citations" in e)


def _say(app, question, answer="Noted.", remembers=None, **body):
    """One /ask, answered with `answer`; the worker then extracts `remembers`."""
    app.model.chat_replies.append([answer])
    app.model.json_replies.append(_extraction(remembers) if remembers else {"memories": [], "summary": "s"})
    status, events = _ask(app, question, **body)
    assert status == 200, events
    assert main.MEMORY_WORKER.wait_idle(10)
    return events


def test_a_new_chat_gets_an_id_and_its_turn_is_saved(app):
    events = _say(app, "When is the midterm?", answer="I couldn't find that.")

    cid = events[0]["conversation_id"]
    assert re.fullmatch(r"c-[0-9a-f]{12}", cid)
    assert events[-1] == {"done": True}
    [turn] = conversations.get_conversation(app.home, COURSE, cid)["turns"]
    assert (turn["question"], turn["answer"], turn["citations"], turn["grounded"]) == (
        "When is the midterm?",
        "I couldn't find that.",
        [],
        False,
    )
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", turn["asked_at"])


def test_the_next_question_in_a_chat_reads_its_history_from_disk(app):
    cid = _say(app, "What kinds of test doubles are there?", answer="Stubs, fakes and mocks.")[0]["conversation_id"]

    # The app's own copy of the chat can be stale; the saved one is used.
    events = _say(app, "Explain the second one.", conversation_id=cid, history=[])

    assert events[0]["conversation_id"] == cid
    sent = app.model.chat_calls[-1]
    assert {"role": "user", "content": "What kinds of test doubles are there?"} in sent
    assert {"role": "assistant", "content": "Stubs, fakes and mocks."} in sent
    assert len(conversations.get_conversation(app.home, COURSE, cid)["turns"]) == 2


@pytest.mark.parametrize("cid", ["c-000000000009", "../../config", "c-1/../../x", 7])
def test_an_unknown_or_unsafe_conversation_id_is_refused_before_any_work(app, cid):
    status, body = _ask(app, "q", conversation_id=cid)

    assert status == 404 and body["error"]["code"] == "not_found"
    assert app.model.chat_calls == []


def test_what_one_chat_told_memory_shapes_the_next_chat(app):
    first = _say(app, "I'm on team 4 with Priya.", remembers="The student is on team 4 with Priya.")

    app.model.chat_replies.append(["Team 4."])
    _, events = _ask(app, "Which team am I on?")

    assert events[0]["conversation_id"] != first[0]["conversation_id"]
    assert "The student is on team 4 with Priya." in app.model.chat_calls[-1][0]["content"]  # profile
    assert [m["text"] for m in _final(events)["memories_used"]] == ["The student is on team 4 with Priya."]


def test_memories_can_be_listed_and_deleted(app):
    _say(app, "I'm auditing the course.", remembers="The student is auditing the course.")

    status, body = _json(app, "GET", f"/courses/{COURSE}/memories")
    assert status == 200
    [m] = body["memories"]
    assert (m["kind"], m["text"], m["status"], m["valid_to"]) == ("fact", "The student is auditing the course.", "active", None)
    assert set(m) == {"id", "kind", "text", "importance", "event_time", "created_at", "valid_to", "status"}

    assert _json(app, "DELETE", f"/courses/{COURSE}/memories/{m['id']}") == (200, {"status": "deleted"})
    assert _json(app, "DELETE", f"/courses/{COURSE}/memories/{m['id']}")[0] == 404
    assert _json(app, "GET", f"/courses/{COURSE}/memories?include_inactive=1") == (200, {"memories": []})


def test_chats_can_be_listed_read_and_deleted_taking_their_memories_along(app):
    cid = _say(app, "I'm auditing the course.", remembers="The student is auditing the course.")[0]["conversation_id"]

    status, body = _json(app, "GET", f"/courses/{COURSE}/conversations")
    assert status == 200 and [c["conversation_id"] for c in body["conversations"]] == [cid]
    status, body = _json(app, "GET", f"/courses/{COURSE}/conversations/{cid}")
    assert status == 200 and body["turns"][0]["question"] == "I'm auditing the course."

    assert _json(app, "DELETE", f"/courses/{COURSE}/conversations/{cid}") == (200, {"status": "deleted"})

    assert _json(app, "GET", f"/courses/{COURSE}/memories?include_inactive=1") == (200, {"memories": []})
    assert _json(app, "GET", f"/courses/{COURSE}/conversations/{cid}")[0] == 404
    assert _json(app, "DELETE", f"/courses/{COURSE}/conversations/{cid}")[0] == 404


def test_an_answer_that_broke_off_is_neither_saved_nor_remembered(app):
    app.model.chat_replies.append(["The midterm is", ConnectionError("model connection dropped")])

    status, events = _ask(app, "When is the midterm?")

    assert status == 200 and any("error" in e for e in events)
    assert conversations.list_conversations(app.home, COURSE) == []
    assert main.MEMORY_WORKER.wait_idle(10)
    assert app.model.json_calls == []


def test_with_memory_switched_off_chats_are_saved_but_nothing_is_remembered(app):
    config.write_config(app.home, {"selected_courses": [COURSE], "memory_enabled": False})
    app.model.chat_replies.append(["Noted."])

    _, events = _ask(app, "I'm on team 4.")

    assert "memories_used" not in _final(events)
    assert main.MEMORY_WORKER.wait_idle(10)
    assert app.model.json_calls == []
    assert conversations.get_conversation(app.home, COURSE, events[0]["conversation_id"])["memory_processed_upto"] == 0


def test_a_memory_failure_never_reaches_the_answer(app):
    app.model.chat_replies.append(["Noted."])
    app.model.json_replies.append(RuntimeError("no OpenAI key stored"))

    status, events = _ask(app, "I'm on team 4.")

    assert status == 200 and events[-1] == {"done": True} and not any("error" in e for e in events)
    assert main.MEMORY_WORKER.wait_idle(10)
    c = conversations.get_conversation(app.home, COURSE, events[0]["conversation_id"])
    assert c["memory_processed_upto"] == 0  # read again after the next restart


def test_turns_left_unread_are_queued_again_at_startup(app):
    turn = {"question": "I'm on team 4.", "answer": "Noted.", "citations": [], "grounded": False, "asked_at": "2026-09-21T18:00:00Z"}
    conversations.append_turn(app.home, COURSE, "c-000000000001", turn)
    app.model.json_replies.append(_extraction("The student is on team 4."))

    main.queue_unread_turns()

    assert main.MEMORY_WORKER.wait_idle(10)
    assert [m["text"] for m in _json(app, "GET", f"/courses/{COURSE}/memories")[1]["memories"]] == ["The student is on team 4."]


@pytest.mark.parametrize(
    "method, path",
    [
        ("GET", "/courses/99999/memories"),
        ("DELETE", "/courses/99999/memories/m-000000000000"),
        ("GET", "/courses/99999/conversations"),
        ("GET", "/courses/99999/conversations/c-000000000001"),
        ("DELETE", "/courses/99999/conversations/c-000000000001"),
    ],
)
def test_memory_and_chat_routes_need_a_selected_course(app, method, path):
    status, body = _json(app, method, path)

    assert status == 404 and body["error"]["code"] == "not_found"
