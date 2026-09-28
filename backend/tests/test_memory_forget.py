"""memory/forget.py's sweep — memories fading to the archive (design spec
§5.7). Archived memories leave recall and the profile but stay listed, so
the student can still see and delete them. Hard deletes are the store's and
MemoryService's own tests."""

from datetime import datetime, timedelta, timezone

import pytest

from memory import forget
from memory.store import MemoryStore

NOW = datetime(2026, 12, 1, 12, 0, tzinfo=timezone.utc)
V = [1.0, 0.0, 0.0]


@pytest.fixture
def store(tmp_path):
    with MemoryStore(tmp_path / "memory.db") as s:
        yield s


def _add(store, kind, days_ago, importance=3, text=None):
    at = NOW - timedelta(days=days_ago)
    return store.add(kind=kind, text=text or f"{kind} {days_ago}", importance=importance, embedding=V, created_at=at, event_time=at)


def _status(store, mid):
    return store.get(mid).status


@pytest.mark.parametrize("kind", ["event", "summary"])
def test_an_ordinary_event_or_summary_fades_after_60_days_unused(store, kind):
    kept = _add(store, kind, days_ago=59)
    faded = _add(store, kind, days_ago=61)

    report = forget.sweep(store, now=NOW)

    assert (_status(store, kept), _status(store, faded)) == ("active", "archived")
    assert report.archived == [faded]


def test_an_important_event_lasts_180_days(store):
    kept = _add(store, "event", days_ago=179, importance=4)
    faded = _add(store, "event", days_ago=181, importance=5)

    forget.sweep(store, now=NOW)

    assert (_status(store, kept), _status(store, faded)) == ("active", "archived")


def test_a_recent_recall_keeps_an_old_event(store):
    mid = _add(store, "event", days_ago=100)
    store.touch([mid], at=NOW - timedelta(days=10))

    forget.sweep(store, now=NOW)

    assert _status(store, mid) == "active"


def test_facts_never_fade_by_age_even_once_replaced(store):
    old = _add(store, "fact", days_ago=400)
    replaced = _add(store, "fact", days_ago=400)
    store.supersede(replaced, by=old, valid_to=NOW - timedelta(days=390))

    assert forget.sweep(store, now=NOW).archived == []
    assert (_status(store, old), _status(store, replaced)) == ("active", "active")


def test_an_open_task_never_fades_but_a_closed_one_goes_30_days_after_closing(store):
    open_task = _add(store, "task", days_ago=300)
    recently_closed = _add(store, "task", days_ago=300)
    long_closed = _add(store, "task", days_ago=300)
    store.invalidate(recently_closed, valid_to=NOW - timedelta(days=29))
    store.invalidate(long_closed, valid_to=NOW - timedelta(days=31))

    forget.sweep(store, now=NOW)

    assert [_status(store, m) for m in (open_task, recently_closed, long_closed)] == ["active", "active", "archived"]


def test_something_that_happens_later_is_not_old(store):
    # "The midterm is on Dec 10", told 90 days ago: its time hasn't come.
    at = NOW - timedelta(days=90)
    mid = store.add(kind="event", text="The midterm is on Dec 10.", importance=3, embedding=V, created_at=at, event_time=NOW + timedelta(days=9))

    forget.sweep(store, now=NOW)

    assert _status(store, mid) == "active"


def test_each_archive_is_logged_once_with_its_rule(store):
    mid = _add(store, "event", days_ago=61)

    forget.sweep(store, now=NOW)
    again = forget.sweep(store, now=NOW + timedelta(days=1))

    assert again.archived == []
    [entry] = [o for o in store.ops() if o["op"] == "ARCHIVE"]
    assert (entry["memory_id"], entry["at"], entry["reason"]) == (mid, NOW, "sweep: event unused 60+ days")


def test_archived_memories_stay_listed_for_the_student(store):
    mid = _add(store, "event", days_ago=61)

    forget.sweep(store, now=NOW)

    assert store.list_memories() == []
    assert [m.id for m in store.list_memories(include_inactive=True)] == [mid]
