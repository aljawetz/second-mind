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


class _FakeModel:
    def transcribe(self, path):
        class Seg:
            start, end, text = 0.0, 2.0, " hello class"

        class Info:
            duration = 2.0

        return iter([Seg()]), Info()


def test_process_session_logs_each_stage_duration(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.setattr(sessions, "_get_model", lambda: _FakeModel())
    monkeypatch.setattr(sessions, "_enhance_notes", lambda text: "notes")
    monkeypatch.setattr(sessions.indexing, "add_nodes", lambda *a, **k: None)
    session_dir = tmp_path / "s1"
    session_dir.mkdir()
    audio = session_dir / "audio.m4a"
    audio.write_bytes(b"x")
    sessions._SESSIONS["s1"] = {"status": "processing", "course_id": 1, "dir": session_dir, "class_num": 1, "source_label": "Class #1"}

    sessions._process_session("s1", audio, tmp_path / "db")

    err = capsys.readouterr().err
    assert "[sessions] s1 transcribe: " in err and "for 2s of audio" in err
    assert "[sessions] s1 summarize: " in err and "for 2 words" in err
    assert "[sessions] s1 index: " in err and "chunks" in err
    assert sessions._SESSIONS["s1"]["status"] == "done"
