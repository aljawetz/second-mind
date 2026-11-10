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


def test_a_turn_the_student_had_forgotten_is_never_indexed(store):
    # forget_memory blocks the turns a forgotten memory came from; a later
    # indexing pass (a restart, or catching up an old chat) must not bring them back.
    store.block_forget_turn("c-1", 0)

    assert _index(store, cid="c-1", turn=0) is False
    assert store.list_turns() == []


def test_deleting_a_chat_removes_only_its_turns(store):
    _index(store, cid="c-1", turn=0)
    _index(store, cid="c-1", turn=1, question="And for standing desks?")
    _index(store, cid="c-2", turn=0, title="Mocks", at=T1)

    assert store.delete_turns("c-1") == 2
    assert [(t.conversation_id, t.turn_index) for t in store.list_turns()] == [("c-2", 0)]


# --- search ---------------------------------------------------------------------

NOW = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
VECTORS = {"posture": [1.0, 0.0, 0.0], "mocks": [0.0, 1.0, 0.0], "kits": [0.0, 0.0, 1.0]}


def topic_embed(text):
    """A turn or query is 'about' the first topic word it contains."""
    for word, vector in VECTORS.items():
        if word in text.lower():
            return vector
    return [0.0, 0.0, 0.0]  # about nothing: only a keyword can find it


def _add(store, cid, turn, question, answer, title="Chat", at=T0):
    assert past_chats.index_turn(
        store, topic_embed, conversation_id=cid, turn_index=turn, title=title, at=at, question=question, answer=answer
    )


def _search(store, query, **kw):
    return past_chats.search(query, store=store, embed=topic_embed, now=NOW, **kw)


def test_search_finds_the_turn_about_the_question(store):
    _add(store, "c-1", 0, "Any posture videos?", "Try the Mayo Clinic one.")
    _add(store, "c-2", 0, "How do mocks work?", "A mock checks calls.")

    assert [(t.conversation_id, t.turn_index) for t in _search(store, "which posture video did you recommend?")] == [("c-1", 0)]


def test_an_exact_word_is_found_even_when_the_meaning_search_misses(store):
    # Neither the turn nor the query has a topic word, so only the keyword matches.
    _add(store, "c-1", 0, "Paint tips?", "For the Tamiya Spitfire use thin coats.")
    _add(store, "c-2", 0, "How do mocks work?", "A mock checks calls.")

    assert [t.conversation_id for t in _search(store, "Tamiya")] == ["c-1"]


def test_the_chat_being_answered_is_left_out(store):
    _add(store, "c-1", 0, "Any posture videos?", "Try the Mayo Clinic one.")
    _add(store, "c-2", 0, "More posture tips?", "Stand up every hour.")

    assert [t.conversation_id for t in _search(store, "posture", skip_conversation="c-1")] == ["c-2"]


def test_unrelated_turns_are_not_returned(store):
    _add(store, "c-1", 0, "How do mocks work?", "A mock checks calls.")

    assert _search(store, "posture") == []


def test_a_newer_turn_comes_before_an_equally_good_older_one(store):
    _add(store, "c-old", 0, "Any posture videos?", "Old answer.", at=datetime(2026, 6, 1, tzinfo=timezone.utc))
    _add(store, "c-new", 0, "Any posture videos?", "New answer.", at=datetime(2026, 9, 30, tzinfo=timezone.utc))

    assert [t.conversation_id for t in _search(store, "posture videos")] == ["c-new", "c-old"]


def test_search_returns_at_most_k_turns(store):
    for i in range(8):
        _add(store, f"c-{i}", 0, "Any posture videos?", f"Answer {i}.")

    assert len(_search(store, "posture")) == past_chats.TOP_K
    assert len(_search(store, "posture", k=2)) == 2


def test_results_show_the_chat_the_date_and_who_said_what(store):
    _add(store, "c-1", 0, "Any posture videos?", "Try the Mayo Clinic one.", title="Posture videos")

    text = past_chats.format_turns(_search(store, "posture"))
    assert text == '[P1] "Posture videos", 2026-09-21\nStudent: Any posture videos?\nAssistant: Try the Mayo Clinic one.'


def test_a_long_past_answer_is_cut_and_labels_continue_across_searches(store):
    _add(store, "c-1", 0, "Any posture videos?", "x" * 2000)

    text = past_chats.format_turns(_search(store, "posture"), first_label=3)
    assert text.startswith("[P3] ")
    assert "x" * past_chats.ANSWER_CHARS + "…" in text and "x" * (past_chats.ANSWER_CHARS + 1) not in text


def test_no_results_says_so(store):
    assert past_chats.format_turns([]) == past_chats.NO_PAST_CHATS


# --- which part of a long past answer is shown -----------------------------------
# The memory evaluation found the right chat 11 times in 12 and still missed:
# the detail asked about sat past the first 600 characters of the answer.

LONG_ANSWER = (
    "Here are some designers. " + "Filler about rings and settings. " * 40
    + "Jessica Poole Jewellery works with unusual gemstones, Instagram @jessicapoolejewellery. "
    + "More filler about polishing. " * 40
)


def test_a_long_answer_is_shown_around_the_words_asked_about(store):
    _add(store, "c-1", 0, "Any posture videos?", LONG_ANSWER)

    text = past_chats.format_turns(_search(store, "posture"), query="Instagram handle designer unusual gemstones")

    assert "@jessicapoolejewellery" in text
    shown = text.split("Assistant: ", 1)[1]
    assert shown.startswith("…") and shown.endswith("…")
    assert len(shown) <= past_chats.ANSWER_CHARS + 2


def test_a_long_answer_with_nothing_matching_shows_its_start(store):
    _add(store, "c-1", 0, "Any posture videos?", LONG_ANSWER)

    shown = past_chats.format_turns(_search(store, "posture"), query="kubernetes").split("Assistant: ", 1)[1]

    assert shown == LONG_ANSWER[: past_chats.ANSWER_CHARS] + "…"


def test_a_short_answer_is_shown_whole_whatever_was_asked(store):
    _add(store, "c-1", 0, "Any posture videos?", "Try the Mayo Clinic one.")

    text = past_chats.format_turns(_search(store, "posture"), query="Mayo Clinic")

    assert text.endswith("Assistant: Try the Mayo Clinic one.")
