"""sessions.py class numbering — real bug from the user's own feedback:
the old implementation counted session directories on disk, which reused
a class number as soon as any session was deleted. class_num must be a
persistent, monotonic counter instead (implementation-plan.md Step 15)."""

import json
import time
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
    """Each chunk's bytes are "<duration>:<text>", e.g. b"60:first part"."""

    def transcribe(self, path, **options):
        self.options = options
        duration, text = Path(path).read_bytes().decode().split(":", 1)

        class Seg:
            start, end = 1.0, 2.0

        Seg.text = f" {text}"

        class Info:
            pass

        Info.duration = float(duration)
        return iter([Seg()]), Info()


def _register(tmp_path: Path, monkeypatch, session_id: str = "s1") -> dict:
    model = _FakeModel()
    monkeypatch.setattr(sessions, "_get_model", lambda: model)
    monkeypatch.setattr(sessions, "_enhance_notes", lambda text: f"notes for: {text}")
    monkeypatch.setattr(sessions.indexing, "add_nodes", lambda *a, **k: None)
    session_dir = tmp_path / session_id
    session_dir.mkdir()
    info = {"status": "recording", "course_id": 1, "dir": session_dir, "class_num": 1, "source_label": "Class #1", "model": model}
    sessions._SESSIONS[session_id] = info
    return info


def _finish(session_id: str, tmp_path: Path) -> None:
    sessions._process_session(session_id, tmp_path / "db", time.perf_counter())


def test_chunks_are_stitched_onto_one_timeline(tmp_path: Path, monkeypatch):
    info = _register(tmp_path, monkeypatch)
    sessions.add_chunk("s1", 0, b"60:first part")
    sessions.add_chunk("s1", 1, b"30:second part")
    _finish("s1", tmp_path)

    segments = json.loads((info["dir"] / "transcript.json").read_text())
    assert [(s["start"], s["text"].strip()) for s in segments] == [(1.0, "first part"), (61.0, "second part")]
    assert (info["dir"] / "summary.md").read_text() == "notes for: first part second part"
    assert info["status"] == "done"


def test_chunk_audio_is_deleted_once_transcribed(tmp_path: Path, monkeypatch):
    info = _register(tmp_path, monkeypatch)
    sessions.add_chunk("s1", 0, b"5:hello")
    _finish("s1", tmp_path)

    assert not list((info["dir"] / "chunks").glob("*.m4a"))


def test_stop_with_a_body_counts_as_the_last_chunk(tmp_path: Path, monkeypatch):
    info = _register(tmp_path, monkeypatch)
    sessions.add_chunk("s1", 0, b"60:one")
    monkeypatch.setattr(sessions.threading, "Thread", lambda target, args, daemon: type("T", (), {"start": lambda self: target(*args)})())
    sessions.stop_session("s1", b"10:two", tmp_path / "db")

    segments = json.loads((info["dir"] / "transcript.json").read_text())
    assert [s["text"].strip() for s in segments] == ["one", "two"]


def test_a_session_with_no_audio_ends_in_error(tmp_path: Path, monkeypatch):
    info = _register(tmp_path, monkeypatch)
    _finish("s1", tmp_path)

    assert info["status"] == "error"
    assert "no audio" in info["error"]


def test_process_session_logs_each_stage_duration(tmp_path: Path, monkeypatch, capsys):
    _register(tmp_path, monkeypatch)
    sessions.add_chunk("s1", 0, b"2:hello class")
    _finish("s1", tmp_path)

    err = capsys.readouterr().err
    assert "[sessions] s1 transcribe chunk 0: " in err and "for 2s of audio" in err
    assert "[sessions] s1 wait for transcription after stop: " in err
    assert "[sessions] s1 summarize: " in err and "for 2 words" in err
    assert "[sessions] s1 index: " in err and "chunks" in err
    assert "[sessions] s1 total after stop: " in err


def test_transcription_skips_silence_and_decodes_greedily(tmp_path: Path, monkeypatch):
    info = _register(tmp_path, monkeypatch)
    sessions.add_chunk("s1", 0, b"2:hello")
    _finish("s1", tmp_path)

    assert info["model"].options == {"beam_size": 1, "vad_filter": True}
