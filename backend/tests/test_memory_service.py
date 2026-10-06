"""memory.MemoryService — the one interface agents use (design spec §7).
Extraction, consolidation and recall each have their own tests; these check
they're wired together. A scripted model and a word-hashing embedder, so no
network and no model files."""

import re
import zlib
from datetime import datetime, timedelta, timezone

import pytest

from memory import MemoryService

T0 = datetime(2026, 9, 8, 18, 30, tzinfo=timezone.utc)
T1 = T0 + timedelta(days=7)
COURSE = 55710


def embed(text):
    """Texts sharing words get similar vectors: enough to exercise the
    wiring without the real model."""
    v = [0.0] * 64
    for word in re.findall(r"\w+", text.lower()):
        v[zlib.crc32(word.encode()) % 64] += 1.0
    return v


class ScriptedLLM:
    def __init__(self, *replies):
        self._replies = list(replies)
        self.calls = []

    def complete_json(self, messages):
        self.calls.append(messages)
        return self._replies.pop(0)


def _extraction(*texts, summary=""):  # no summary memory unless a test wants one
    return {
        "memories": [
            {"kind": "fact", "text": t, "importance": 4, "event_time": None, "entities": ["team"], "task_ref_hint": None}
            for t in texts
        ],
        "summary": summary,
    }


def _turn(question, answer="OK."):
    return [{"role": "user", "content": question}, {"role": "assistant", "content": answer}]


@pytest.fixture
def clock():
    now = {"t": T0}
    return now


@pytest.fixture
def service_for(tmp_path, clock):
    opened = []

    def make(llm):
        svc = MemoryService(tmp_path, COURSE, llm=llm, embed=embed, now=lambda: clock["t"])
        opened.append(svc)
        return svc

    yield make
    for svc in opened:
        svc.close()


def test_what_the_student_said_can_be_recalled_later(service_for, clock):
    svc = service_for(ScriptedLLM(_extraction("The student is on team 4 with Priya and Ken.", summary="Talked about the project.")))

    result = svc.observe(_turn("I'm on team 4 with Priya and Ken."), conversation_id="c-1", turn_index=0)
    clock["t"] = T1
    hits = svc.recall("Am I on team 4 with Priya and Ken?")

    assert result.summary == "Talked about the project."
    assert [h.memory.text for h in hits] == ["The student is on team 4 with Priya and Ken."]
    assert hits[0].memory.provenance == [("c-1", 0)]
    assert hits[0].memory.created_at == T0


def test_memory_is_kept_in_the_course_directory(service_for, tmp_path):
    service_for(ScriptedLLM())

    assert (tmp_path / "courses" / str(COURSE) / "memory.db").exists()


def test_a_changed_fact_replaces_the_old_one_through_consolidation(service_for, clock):
    llm = ScriptedLLM(
        _extraction("The student's team does the recommender project."),
        _extraction("The student's team switched to the fraud detection project."),
        {"decision": "UPDATE", "target": 1},
    )
    svc = service_for(llm)

    svc.observe(_turn("We picked the recommender project."), conversation_id="c-1", turn_index=0)
    clock["t"] = T1
    result = svc.observe(_turn("We switched to fraud detection."), conversation_id="c-2", turn_index=0)

    assert [d.action for d in result.decisions] == ["UPDATE"]
    assert [h.memory.text for h in svc.recall("Which project does the student's team do?")] == [
        "The student's team switched to the fraud detection project."
    ]
    history = svc.recall("Which project did the student's team do before?", include_history=True)
    assert {h.memory.text for h in history} == {
        "The student's team does the recommender project.",
        "The student's team switched to the fraud detection project.",
    }


def test_the_summary_so_far_goes_to_extraction_and_drops_are_reported(service_for):
    llm = ScriptedLLM(_extraction("The student got a 72 on the midterm.", summary="New summary."))
    svc = service_for(llm)

    result = svc.observe(_turn("I got a 72 on the midterm."), conversation_id="c-1", turn_index=3, summary="Old summary.")

    assert "Old summary." in llm.calls[0][-1]["content"]
    assert result.summary == "New summary."
    assert result.dropped == [("The student got a 72 on the midterm.", "grades_or_deadlines")]
    assert [m.text for m in svc.list()] == ["New summary."]  # the chat's summary, not the grade


def test_the_profile_comes_from_the_same_store(service_for):
    svc = service_for(ScriptedLLM(_extraction("The student wants code examples in Java.")))
    svc.observe(_turn("Use Java for examples please."), conversation_id="c-1", turn_index=0)

    assert "The student wants code examples in Java." in svc.profile_block()


def test_forgetting_by_id_really_deletes_and_skips_unknown_ids(service_for):
    svc = service_for(ScriptedLLM(_extraction("The student is auditing the course.", "The student wants code examples in Java.")))
    svc.observe(_turn("I'm auditing. Use Java."), conversation_id="c-1", turn_index=0)
    auditing = next(m.id for m in svc.list() if "auditing" in m.text)

    assert svc.forget([auditing, "m-000000000000"]) == 1

    assert [m.text for m in svc.list(include_inactive=True)] == ["The student wants code examples in Java."]
    assert all("auditing" not in h.memory.text for h in svc.recall("Am I auditing the course?"))


def test_a_student_edit_rewrites_text_and_embedding(service_for):
    svc = service_for(ScriptedLLM(_extraction("The student is on team 4.")))
    svc.observe(_turn("Team 4."), conversation_id="c-1", turn_index=0)
    mid = svc.list()[0].id

    updated = svc.update_text(mid, "The student is on team 5.")

    assert updated is not None and updated.text == "The student is on team 5."
    assert svc.list()[0].text == "The student is on team 5."


def test_a_student_edit_rejects_superseded_memories(service_for):
    svc = service_for(ScriptedLLM(_extraction("The student is on team 4.")))
    svc.observe(_turn("Team 4."), conversation_id="c-1", turn_index=0)
    old_id = svc.list()[0].id
    new_id = svc._store.add(
        kind="fact",
        text="The student is on team 5.",
        importance=4,
        embedding=embed("The student is on team 5."),
        created_at=T0,
        provenance=[("c-1", 1)],
        reason="test",
    )
    svc._store.supersede(old_id, by=new_id, valid_to=T1)

    with pytest.raises(ValueError, match="inactive"):
        svc.update_text(old_id, "Changed.")


def test_deleting_a_chat_forgets_what_came_only_from_it(service_for, clock):
    llm = ScriptedLLM(
        _extraction("The student is on team 4 with Priya and Ken."),
        _extraction("The student wants code examples in Java."),
        _extraction("The student is on team 4 with Priya and Ken."),
        {"decision": "NOOP", "target": 1},
    )
    svc = service_for(llm)
    svc.observe(_turn("I'm on team 4 with Priya and Ken."), conversation_id="c-1", turn_index=0)
    svc.observe(_turn("Use Java."), conversation_id="c-1", turn_index=1)
    svc.observe(_turn("Team 4 again, with Priya and Ken."), conversation_id="c-2", turn_index=0)

    assert svc.forget_conversation("c-1") == 1

    # Said again in c-2, so the team fact stays; Java came only from c-1.
    assert [m.text for m in svc.list(include_inactive=True)] == ["The student is on team 4 with Priya and Ken."]


def test_a_turn_read_later_is_dated_when_it_was_said(service_for, clock):
    # After a restart the worker reads turns asked days ago; "last Tuesday"
    # must be worked out from when the student said it.
    llm = ScriptedLLM(_extraction("The student missed Class #5."))
    svc = service_for(llm)
    clock["t"] = T1

    svc.observe(_turn("I missed class last Tuesday."), conversation_id="c-1", turn_index=0, at=T0)

    assert "Tuesday 2026-09-08" in llm.calls[0][-1]["content"]
    assert svc.list()[0].created_at == T0


def test_a_sweep_fades_what_went_unused_by_the_service_clock(service_for, clock):
    reply = _extraction("The student missed Class #5.")
    reply["memories"][0]["kind"] = "event"
    reply["memories"][0]["importance"] = 3
    svc = service_for(ScriptedLLM(reply))
    svc.observe(_turn("I missed class 5."), conversation_id="c-1", turn_index=0)

    clock["t"] = T0 + timedelta(days=61)
    report = svc.sweep()

    assert len(report.archived) == 1
    assert svc.list() == [] and svc.list(include_inactive=True)[0].status == "archived"


def test_each_turn_rewrites_its_chat_summary_as_one_memory(service_for, clock):
    llm = ScriptedLLM(
        _extraction("The student is on team 4 with Priya and Ken.", summary="Asked which team does the fixtures lab."),
        {"memories": [], "summary": "Asked about the fixtures lab, then about mocking the email service."},
    )
    svc = service_for(llm)
    svc.observe(_turn("Which team does the fixtures lab?"), conversation_id="c-1", turn_index=0)
    clock["t"] = T1
    svc.observe(_turn("How do I mock the email service?"), conversation_id="c-1", turn_index=1)

    [summary] = [m for m in svc.list() if m.kind == "summary"]
    assert (summary.text, summary.conversation_id) == ("Asked about the fixtures lab, then about mocking the email service.", "c-1")
    assert [h.memory.id for h in svc.recall("What did we say about mocking the email service?")] == [summary.id]


def test_the_chat_being_answered_does_not_recall_its_own_summary(tmp_path, clock):
    llm = ScriptedLLM({"memories": [], "summary": "Asked about mocking the email service."})
    with MemoryService(tmp_path, COURSE, llm=llm, embed=embed, now=lambda: clock["t"]) as svc:
        svc.observe(_turn("How do I mock the email service?"), conversation_id="c-1", turn_index=0)
    with MemoryService(tmp_path, COURSE, llm=llm, embed=embed, now=lambda: clock["t"], conversation_id="c-1") as same_chat:
        assert same_chat.recall("mocking email") == []
    with MemoryService(tmp_path, COURSE, llm=llm, embed=embed, now=lambda: clock["t"], conversation_id="c-2") as other_chat:
        assert len(other_chat.recall("mocking email")) == 1


def _service_reporting_forgets(tmp_path, clock, *replies):
    cleared = []
    svc = MemoryService(tmp_path, COURSE, llm=ScriptedLLM(*replies), embed=embed, now=lambda: clock["t"], on_forget=cleared.append)
    return svc, cleared


def test_forgetting_a_fact_forgets_its_chats_summaries_and_says_which_chats(tmp_path, clock):
    # A chat's summary may repeat the fact, and so may the chat's running
    # summary, which would write it back on the next turn.
    svc, cleared = _service_reporting_forgets(
        tmp_path, clock,
        _extraction("The student is auditing the course.", summary="Said they are auditing."),
        _extraction("The student wants code examples in Java.", summary="Asked for Java."),
    )
    with svc:
        svc.observe(_turn("I'm auditing."), conversation_id="c-1", turn_index=0)
        svc.observe(_turn("Use Java."), conversation_id="c-2", turn_index=0)
        auditing = next(m.id for m in svc.list() if "auditing" in m.text and m.kind == "fact")

        assert svc.forget([auditing]) == 1

        assert sorted(m.text for m in svc.list(include_inactive=True)) == ["Asked for Java.", "The student wants code examples in Java."]
        assert cleared == [["c-1"]]


def test_forgetting_a_chat_summary_itself_clears_that_chats_running_summary(tmp_path, clock):
    svc, cleared = _service_reporting_forgets(tmp_path, clock, {"memories": [], "summary": "Said they are auditing."})
    with svc:
        svc.observe(_turn("I'm auditing."), conversation_id="c-1", turn_index=0)
        [summary] = svc.list()

        assert svc.forget([summary.id]) == 1
        assert cleared == [["c-1"]]


def test_forgetting_nothing_reports_no_chats(tmp_path, clock):
    svc, cleared = _service_reporting_forgets(tmp_path, clock)
    with svc:
        assert svc.forget(["m-000000000000"]) == 0
        assert cleared == []
