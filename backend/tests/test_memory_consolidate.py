"""memory/consolidate.py — deciding what a new memory does to the ones
already stored (design spec §5.3). A scripted model gives the decision and
a lookup table gives the embeddings, so each test controls exactly which
memories count as similar."""

from datetime import datetime, timezone

import pytest

from memory import consolidate
from memory.extract import Candidate
from memory.store import MemoryStore

T0 = datetime(2026, 9, 8, 18, 30, tzinfo=timezone.utc)
T1 = datetime(2026, 9, 15, 20, 0, tzinfo=timezone.utc)

RECOMMENDER = "The student's team does the recommender project."
FRAUD = "The student's team switched to the fraud-detection project."
JAVA = "The student wants code examples in Java."
# cos(RECOMMENDER, FRAUD) ≈ 0.95, above the 0.70 bar; JAVA is orthogonal to both.
VECTORS = {RECOMMENDER: [1.0, 0.0, 0.0], FRAUD: [0.9, 0.3, 0.0], JAVA: [0.0, 0.0, 1.0]}


class ScriptedLLM:
    def __init__(self, *replies):
        self._replies = list(replies)
        self.calls = []

    def complete_json(self, messages):
        self.calls.append(messages)
        return self._replies.pop(0)


@pytest.fixture
def store(tmp_path):
    with MemoryStore(tmp_path / "memory.db") as s:
        yield s


def _stored(store, text, kind="fact", at=T0):
    return store.add(
        kind=kind, text=text, importance=3, embedding=VECTORS[text], created_at=at, event_time=at,
        provenance=[("c-1", 0)], reason="new",
    )


def _candidate(text, kind="fact", at=T1, importance=4):
    return Candidate(kind=kind, text=text, importance=importance, event_time=at, entities=["team"], task_ref_hint=None)


def _consolidate(store, candidate, llm):
    return consolidate.consolidate(
        candidate, store=store, embed=VECTORS.__getitem__, llm=llm, at=T1, provenance=[("c-2", 1)]
    )


def test_a_memory_like_no_other_is_added_without_asking_the_model(store):
    _stored(store, JAVA)
    llm = ScriptedLLM()

    decision = _consolidate(store, _candidate(FRAUD), llm)

    assert llm.calls == []
    assert decision.action == "ADD"
    m = store.get(decision.memory_id)
    assert (m.kind, m.text, m.importance, m.event_time, m.created_at) == ("fact", FRAUD, 4, T1, T1)
    assert (m.entities, m.provenance) == (["team"], [("c-2", 1)])
    assert m.embedding == pytest.approx(VECTORS[FRAUD])


def test_the_model_sees_the_new_memory_and_its_similar_neighbours_numbered_and_dated(store):
    _stored(store, RECOMMENDER)
    _stored(store, JAVA)
    llm = ScriptedLLM({"decision": "NOOP", "target": 1})

    _consolidate(store, _candidate(FRAUD), llm)

    sent = llm.calls[0][-1]["content"]
    assert FRAUD in sent and "2026-09-15" in sent
    assert f"1. (fact, since 2026-09-08) {RECOMMENDER}" in sent
    assert JAVA not in sent  # not similar enough to be worth the comparison


def test_memories_of_another_kind_are_not_compared(store):
    _stored(store, RECOMMENDER, kind="task")
    llm = ScriptedLLM()

    decision = _consolidate(store, _candidate(FRAUD, kind="fact"), llm)

    assert (llm.calls, decision.action) == ([], "ADD")


def test_a_memory_that_was_already_replaced_is_not_compared_again(store):
    old = _stored(store, RECOMMENDER)
    store.supersede(old, by=_stored(store, JAVA), valid_to=T0)
    llm = ScriptedLLM()

    decision = _consolidate(store, _candidate(FRAUD), llm)

    assert (llm.calls, decision.action) == ([], "ADD")


def _all_ids(store):
    return {m.id for m in store.list_memories(include_inactive=True)}


def test_update_replaces_the_old_memory_and_keeps_it_dated(store):
    old = _stored(store, RECOMMENDER)

    decision = _consolidate(store, _candidate(FRAUD), ScriptedLLM({"decision": "UPDATE", "target": 1}))

    assert decision.action == "UPDATE"
    assert store.get(decision.memory_id).text == FRAUD
    replaced = store.get(old)
    assert (replaced.superseded_by, replaced.valid_to) == (decision.memory_id, T1)
    assert [(o["op"], o["memory_id"], o["reason"]) for o in store.ops()][1:] == [
        ("ADD", decision.memory_id, "consolidation: UPDATE"),
        ("SUPERSEDE", old, "consolidation: UPDATE"),
    ]


def test_invalidate_ends_the_old_memory_and_stores_nothing_new(store):
    old = _stored(store, RECOMMENDER)

    decision = _consolidate(store, _candidate(FRAUD), ScriptedLLM({"decision": "INVALIDATE", "target": 1}))

    assert (decision.action, decision.memory_id) == ("INVALIDATE", None)
    assert store.get(old).valid_to == T1 and store.get(old).superseded_by is None
    assert _all_ids(store) == {old}


def test_noop_strengthens_the_memory_and_records_where_it_was_said_again(store):
    old = _stored(store, RECOMMENDER)

    decision = _consolidate(store, _candidate(FRAUD), ScriptedLLM({"decision": "NOOP", "target": 1}))

    assert (decision.action, decision.memory_id) == ("NOOP", None)
    m = store.get(old)
    assert m.importance == 4
    assert m.provenance == [("c-1", 0), ("c-2", 1)]  # deleting c-1 alone no longer removes it
    assert _all_ids(store) == {old}


def test_add_after_asking_keeps_both(store):
    old = _stored(store, RECOMMENDER)

    decision = _consolidate(store, _candidate(FRAUD), ScriptedLLM({"decision": "ADD", "target": None}))

    assert decision.action == "ADD"
    assert _all_ids(store) == {old, decision.memory_id}
    assert store.get(old).valid_to is None


@pytest.mark.parametrize(
    "reply",
    [
        {"decision": "MERGE", "target": 1},
        {"decision": "UPDATE", "target": 2},  # only one neighbour was shown
        {"decision": "UPDATE", "target": 0},
        {"decision": "UPDATE"},
        {"decision": "NOOP", "target": "first"},
        None,
        "UPDATE 1",
    ],
)
def test_an_unusable_decision_falls_back_to_adding(store, reply):
    # A duplicate can be cleaned up later; a lost fact can't be recovered.
    old = _stored(store, RECOMMENDER)

    decision = _consolidate(store, _candidate(FRAUD), ScriptedLLM(reply))

    assert decision.action == "ADD"
    assert _all_ids(store) == {old, decision.memory_id}
    assert store.get(old).valid_to is None
    assert store.ops()[-1]["reason"] == "consolidation: fallback"
