"""sessions.py class numbering — real bug from the user's own feedback:
the old implementation counted session directories on disk, which reused
a class number as soon as any session was deleted. class_num must be a
persistent, monotonic counter instead (implementation-plan.md Step 15)."""

from pathlib import Path

import sessions


def test_class_num_starts_at_one_and_increments(tmp_path: Path):
    first = sessions.start_session(tmp_path, 111)
    second = sessions.start_session(tmp_path, 111)
    third = sessions.start_session(tmp_path, 111)

    assert first["class_num"] == 1
    assert second["class_num"] == 2
    assert third["class_num"] == 3
    assert first["title"] == "Class #1"


def test_class_num_is_not_reused_after_delete(tmp_path: Path):
    db_path = tmp_path / "index.lancedb"
    first = sessions.start_session(tmp_path, 111)
    second = sessions.start_session(tmp_path, 111)

    sessions.delete_session(tmp_path, 111, second["session_id"], db_path)
    third = sessions.start_session(tmp_path, 111)

    assert first["class_num"] == 1
    assert second["class_num"] == 2
    assert third["class_num"] == 3  # not 2 again, even though session #2 is gone


def test_counter_is_per_course(tmp_path: Path):
    a = sessions.start_session(tmp_path, 111)
    b = sessions.start_session(tmp_path, 222)

    assert a["class_num"] == 1
    assert b["class_num"] == 1


def test_list_sessions_and_detail_expose_class_num(tmp_path: Path):
    started = sessions.start_session(tmp_path, 111)

    listed = sessions.list_sessions(tmp_path, 111)
    assert listed[0]["class_num"] == 1
    assert listed[0]["title"] == "Class #1"

    detail = sessions.get_session_detail(tmp_path, 111, started["session_id"])
    assert detail["class_num"] == 1
