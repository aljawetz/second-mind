"""memory/store.py — the SQLite layer under agent memory (design:
docs/superpowers/specs/2026-09-25-agent-memory-design.md §4). Short plain
vectors stand in for embeddings, so these tests need no model files."""

from datetime import datetime, timezone

import pytest

from memory.store import MemoryStore

T0 = datetime(2026, 9, 21, 18, 0, tzinfo=timezone.utc)
T1 = datetime(2026, 9, 22, 9, 30, tzinfo=timezone.utc)
T2 = datetime(2026, 9, 23, 20, 15, tzinfo=timezone.utc)
X = [1.0, 0.0, 0.0]


@pytest.fixture
def store(tmp_path):
    with MemoryStore(tmp_path / "memory.db") as s:
        yield s


def _add(store, text="The student is on team 4.", kind="fact", vec=X, **kw):
    kw.setdefault("importance", 3)
    kw.setdefault("created_at", T0)
    return store.add(kind=kind, text=text, embedding=list(vec), **kw)


def test_added_memory_reads_back_with_all_its_fields(store):
    mid = _add(store, importance=4, event_time=T0, entities=["Team 4", " Priya "], provenance=[("c-abc", 0)])

    m = store.get(mid)
    assert mid.startswith("m-")
    assert (m.kind, m.text, m.importance) == ("fact", "The student is on team 4.", 4)
    assert (m.event_time, m.created_at) == (T0, T0)
    assert (m.valid_to, m.superseded_by, m.status) == (None, None, "active")
    assert (m.access_count, m.last_accessed) == (0, None)
    assert sorted(m.entities) == ["priya", "team 4"]
    assert m.provenance == [("c-abc", 0)]
    assert m.embedding == pytest.approx(X)


def test_unknown_memory_is_none(store):
    assert store.get("m-000000000000") is None


def test_unknown_kind_is_rejected(store):
    with pytest.raises(ValueError):
        _add(store, kind="opinion")


def test_memories_survive_reopening_the_file(store, tmp_path):
    mid = _add(store)
    store.close()

    with MemoryStore(tmp_path / "memory.db") as reopened:
        assert reopened.get(mid).text == "The student is on team 4."


def _ids(hits):
    return [m.id for m, _score in hits]


def test_vector_search_ranks_by_cosine_similarity(store):
    _add(store, "far", vec=[0.0, 1.0, 0.0])
    near = _add(store, "near", vec=[0.9, 0.3, 0.0])
    # Not unit length: ranking must be by cosine, not raw dot product.
    same_direction = _add(store, "same direction", vec=[3.0, 0.0, 0.0])

    hits = store.vector_search(X, k=2)
    assert _ids(hits) == [same_direction, near]
    assert hits[0][1] == pytest.approx(1.0)


def test_vector_search_on_an_empty_store_finds_nothing(store):
    assert store.vector_search(X, k=5) == []


def test_keyword_search_finds_memories_sharing_a_word(store):
    email = _add(store, "The student is stuck mocking the email service.")
    _add(store, "The student wants code examples in Java.")

    assert _ids(store.keyword_search("email", k=5)) == [email]


def test_keyword_search_takes_the_students_raw_words(store):
    # Quotes, "NOT", "*", ":" and "-" are all FTS5 query syntax; passed
    # through as-is they raise "fts5: syntax error" instead of searching.
    a3 = _add(store, "The student finished part 1 of A3.")

    hits = store.keyword_search('what\'s left on "A3"? (part-2) NOT done: *', k=5)
    assert _ids(hits) == [a3]
    assert store.keyword_search("?! ...", k=5) == []


def test_searches_can_be_limited_to_some_kinds(store):
    _add(store, "The student likes the email lecture.", kind="fact")
    task = _add(store, "The student is mocking the email service.", kind="task")

    assert _ids(store.vector_search(X, k=5, kinds=("task",))) == [task]
    assert _ids(store.keyword_search("email", k=5, kinds=("task",))) == [task]


def test_superseded_memory_is_found_only_when_history_is_asked_for(store):
    old = _add(store, "The team does the recommender project.")
    new = _add(store, "The team does the fraud-detection project.")

    store.supersede(old, by=new, valid_to=T1)

    m = store.get(old)
    assert (m.valid_to, m.superseded_by) == (T1, new)
    assert _ids(store.vector_search(X, k=5)) == [new]
    assert _ids(store.keyword_search("project", k=5)) == [new]
    assert set(_ids(store.vector_search(X, k=5, include_history=True))) == {old, new}
    assert set(_ids(store.keyword_search("project", k=5, include_history=True))) == {old, new}


def test_invalidated_memory_ends_without_a_successor(store):
    mid = _add(store)

    store.invalidate(mid, valid_to=T1)

    m = store.get(mid)
    assert (m.valid_to, m.superseded_by) == (T1, None)
    assert store.vector_search(X, k=5) == []


def test_archived_memory_is_left_out_even_with_history(store):
    mid = _add(store, "The student missed Class #5.", kind="event")

    store.archive(mid, at=T1)

    assert store.get(mid).status == "archived"
    assert store.vector_search(X, k=5, include_history=True) == []
    assert store.keyword_search("class", k=5, include_history=True) == []


def test_touch_counts_each_use_and_when_it_was(store):
    a = _add(store, "a")
    b = _add(store, "b")

    store.touch([a], at=T1)
    store.touch([a, b], at=T2)

    assert (store.get(a).access_count, store.get(a).last_accessed) == (2, T2)
    assert (store.get(b).access_count, store.get(b).last_accessed) == (1, T2)


def test_importance_bumps_stop_at_five(store):
    mid = _add(store, importance=4)

    store.bump_importance(mid, at=T1)
    store.bump_importance(mid, at=T2)

    assert store.get(mid).importance == 5


def test_every_change_is_logged_with_its_reason(store):
    old = _add(store, "old", reason="extraction")
    new = _add(store, "new", created_at=T1, reason="consolidation")
    store.supersede(old, by=new, valid_to=T1, reason="consolidation")
    store.bump_importance(new, at=T1, reason="consolidation NOOP")
    store.invalidate(new, valid_to=T2, reason="consolidation")
    store.archive(old, at=T2, reason="sweep")

    assert [(o["at"], o["op"], o["memory_id"], o["reason"]) for o in store.ops()] == [
        (T0, "ADD", old, "extraction"),
        (T1, "ADD", new, "consolidation"),
        (T1, "SUPERSEDE", old, "consolidation"),
        (T1, "BUMP", new, "consolidation NOOP"),
        (T2, "INVALIDATE", new, "consolidation"),
        (T2, "ARCHIVE", old, "sweep"),
    ]


def _rows(tmp_path, sql):
    """Reads the file directly, the way anything else on the machine could."""
    import sqlite3

    conn = sqlite3.connect(tmp_path / "memory.db")
    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


def test_delete_removes_the_memory_and_everything_that_points_at_it(store, tmp_path):
    gone = _add(store, "The student is on team 4 with Priya.", entities=["priya", "team 4"], provenance=[("c-1", 0)], reason="extraction")
    kept = _add(store, "The student's teammate Ken likes Java.", entities=["team 4", "ken"], provenance=[("c-2", 0)])

    store.delete(gone, at=T1, reason="student asked to forget")

    assert store.get(gone) is None
    assert store.keyword_search("priya", k=5) == []
    assert _rows(tmp_path, "SELECT memory_id FROM provenance") == [(kept,)]
    # An entity name used only by the deleted memory is itself personal data.
    assert sorted(r[0] for r in _rows(tmp_path, "SELECT name FROM entity")) == ["ken", "team 4"]
    assert all(o["memory_id"] != gone for o in store.ops())
    assert store.ops()[-1] == {"at": T1, "op": "DELETE", "memory_id": None, "reason": "student asked to forget"}


def test_deleting_a_newer_fact_leaves_the_older_one_superseded(store):
    old = _add(store, "The team does the recommender project.")
    new = _add(store, "The team does the fraud-detection project.")
    store.supersede(old, by=new, valid_to=T1)

    store.delete(new, at=T2)

    m = store.get(old)
    assert (m.valid_to, m.superseded_by) == (T1, None)
    assert store.vector_search(X, k=5) == []


def test_deleted_text_is_not_left_in_the_database_files(store, tmp_path):
    # Unqueryable isn't enough: SQLite keeps deleted rows in free pages and
    # in the write-ahead log, and FTS5 keeps deleted words in its index
    # until segments merge. Anything that reads the file (a backup, a disk
    # image) would still find them. Checked while the store is open,
    # the way the app would be running.
    gone = _add(store, "The student told the assistant qzxjvkwp in confidence.", entities=["qzxjvkwp"])
    for i in range(30):
        _add(store, f"Unrelated memory number {i} about testing.")

    store.delete(gone, at=T1)

    for f in tmp_path.iterdir():
        assert b"qzxjvkwp" not in f.read_bytes(), f"found in {f.name}"


def test_memories_that_came_only_from_one_chat_are_found_for_the_cascade(store):
    only_c1 = _add(store, "a", provenance=[("c-1", 0), ("c-1", 2)])
    _add(store, "b", provenance=[("c-1", 1), ("c-2", 0)])  # also said in c-2: survives deleting c-1
    _add(store, "c", provenance=[("c-2", 3)])
    summary_c1 = _add(store, "Summary of c-1.", kind="summary", conversation_id="c-1")

    assert set(store.memories_only_from("c-1")) == {only_c1, summary_c1}


def test_listing_shows_current_memories_newest_first_or_everything_on_request(store):
    ended = _add(store, "a", created_at=T0)
    archived = _add(store, "b", created_at=T1)
    current = _add(store, "c", created_at=T2)
    store.invalidate(ended, valid_to=T2)
    store.archive(archived, at=T2)

    assert [m.id for m in store.list_memories()] == [current]
    assert [m.id for m in store.list_memories(include_inactive=True)] == [current, archived, ended]


def test_store_closes_its_file_at_the_end_of_a_with_block(tmp_path):
    import sqlite3

    with MemoryStore(tmp_path / "memory.db") as store:
        _add(store)

    with pytest.raises(sqlite3.ProgrammingError):
        store.get("m-000000000000")


def test_a_memory_said_again_in_another_chat_survives_deleting_the_first(store):
    mid = _add(store, provenance=[("c-1", 0)])

    store.add_provenance(mid, [("c-2", 3)])

    assert store.get(mid).provenance == [("c-1", 0), ("c-2", 3)]
    assert store.memories_only_from("c-1") == []


def test_keyword_search_ignores_words_that_every_memory_shares(store):
    # Memories are written "The student …" (design spec §5.2): "the", "is"
    # and "student" match all of them, and recall counts a keyword match by
    # rank alone, so these would pull every memory into every chat turn.
    team = _add(store, "The student is on team 4 with Priya.")
    _add(store, "The student wants code examples in Java.")

    assert store.keyword_search("When is the midterm?", k=5) == []
    assert store.keyword_search("What did the student say?", k=5) == []
    assert _ids(store.keyword_search("Which team is the student on?", k=5)) == [team]
    assert _ids(store.keyword_search("team 4", k=5)) == [team]
