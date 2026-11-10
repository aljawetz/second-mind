"""memory/past_chats.py — the index of saved chat turns behind
search_past_chats (design: docs/specs/2026-11-10-past-chat-search-design.md).
Short plain vectors stand in for embeddings, so these tests need no model."""

from datetime import datetime, timezone

import pytest

from memory import past_chats
from memory.store import MemoryStore

T0 = datetime(2026, 9, 21, 18, 0, tzinfo=timezone.utc)
T1 = datetime(2026, 9, 22, 9, 30, tzinfo=timezone.utc)


def embed(text):
    return [1.0, 0.0, 0.0]


@pytest.fixture
def store(tmp_path):
    with MemoryStore(tmp_path / "memory.db") as s:
        yield s


def _index(store, cid="c-1", turn=0, question="Any posture videos?", answer="Try the Mayo Clinic one.", **kw):
    kw.setdefault("title", "Posture videos")
    kw.setdefault("at", T0)
    return past_chats.index_turn(store, embed, conversation_id=cid, turn_index=turn, question=question, answer=answer, **kw)


def test_an_indexed_turn_reads_back_with_who_said_what(store):
    assert _index(store) is True

    [turn] = store.list_turns()
    assert (turn.conversation_id, turn.turn_index, turn.title, turn.at) == ("c-1", 0, "Posture videos", T0)
    assert turn.question == "Any posture videos?"
    assert turn.answer == "Try the Mayo Clinic one."


def test_indexing_the_same_turn_again_replaces_it(store):
    _index(store, answer="First answer.")
    _index(store, answer="Second answer.")

    assert [t.answer for t in store.list_turns()] == ["Second answer."]


def test_old_citation_numbers_are_not_kept(store):
    _index(store, answer="Stubs, fakes [1][2] and mocks [3].")

    assert store.list_turns()[0].answer == "Stubs, fakes and mocks."


@pytest.mark.parametrize(
    "question,answer",
    [
        ("I got a 72 on the midterm, is that ok?", "It depends on the curve."),
        ("When is A3?", "Assignment 3 is due Friday."),
        ("How did I do?", "You scored 18/20 on Lab 1."),
    ],
)
def test_a_turn_that_mentions_grades_or_deadlines_is_not_indexed(store, question, answer):
    # Design §7 decision 1: the memory database holds no grades or deadlines.
    assert _index(store, question=question, answer=answer) is False
    assert store.list_turns() == []


def test_a_turn_that_becomes_a_grade_turn_is_removed_when_reindexed(store):
    _index(store, answer="A fake is a working stand-in.")
    _index(store, answer="A fake is a working stand-in. You got 85% on that quiz.")

    assert store.list_turns() == []


def test_deleting_a_chat_removes_only_its_turns(store):
    _index(store, cid="c-1", turn=0)
    _index(store, cid="c-1", turn=1, question="And for standing desks?")
    _index(store, cid="c-2", turn=0, title="Mocks", at=T1)

    assert store.delete_turns("c-1") == 2
    assert [(t.conversation_id, t.turn_index) for t in store.list_turns()] == [("c-2", 0)]
