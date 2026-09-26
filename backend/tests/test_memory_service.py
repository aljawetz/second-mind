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


def _extraction(*texts, summary="Talked about the project."):
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
    svc = service_for(ScriptedLLM(_extraction("The student is on team 4 with Priya and Ken.")))

    result = svc.observe(_turn("I'm on team 4 with Priya and Ken."), conversation_id="c-1", turn_index=0)
    clock["t"] = T1
    hits = svc.recall("Which team am I on?")

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
    assert [h.memory.text for h in svc.recall("Which project is my team doing?")] == [
        "The student's team switched to the fraud detection project."
    ]
    history = svc.recall("Which project did my team do before?", include_history=True)
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
    assert svc.list() == []


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
