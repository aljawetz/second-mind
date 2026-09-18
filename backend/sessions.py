"""Session capture — implementation-plan.md Step 12, design spec §9.3.

Manually triggered via a "+" in the UI, not design spec §9.2's
scheduled-window auto-prompt (that needs a whole weekly-schedule
onboarding step, §9.1, that doesn't exist — see implementation-plan.md's
Step 12 update for the real scope decision).

Recording itself happens in the frontend (getUserMedia/MediaRecorder) —
this module handles everything after: saving the uploaded audio,
transcribing it locally and fully offline (faster-whisper, model bundled
the same way as the BGE embedding model), generating transcript-only
enhanced notes, indexing transcript + the student's own notes for Q&A,
and deleting the raw audio once transcription succeeds (data-model.md
§1 — the same "don't keep raw source material longer than needed" policy
already applied to Canvas files).

Session state is read from disk, not just the in-memory _SESSIONS dict —
a real gap found in manual testing: the dict alone doesn't survive an app
restart, so a session from a previous run would otherwise vanish even
though its files are still sitting right there on disk.
"""

import json
import shutil
import threading
import traceback
from datetime import date
from pathlib import Path

from faster_whisper import WhisperModel
from llama_index.core.prompts import PromptTemplate
from llama_index.llms.openai import OpenAI

import generation
import indexing

MODEL_DIR = Path(__file__).parent / "models" / "faster-whisper-base"

_model: WhisperModel | None = None
_model_lock = threading.Lock()


def _get_model() -> WhisperModel:
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:
                _model = WhisperModel(str(MODEL_DIR), device="cpu", compute_type="int8")
    return _model


# Real finding from manual testing: gpt-4o-mini, given only a few seconds of
# transcript mentioning a recognizable topic (e.g. "system architecture"),
# would write a full textbook-style explanation of that topic from its own
# training knowledge rather than just what was actually said. The first
# version of this prompt's "don't add information that isn't in the
# transcript" wasn't strong enough — this one is explicit that brief
# mentions must stay brief, not expanded using outside knowledge. A prompt
# fix reduces this; it doesn't guarantee zero hallucination from an LLM.
SUMMARY_TEMPLATE = PromptTemplate(
    "You are SSB, a study assistant. The following is a raw transcript of a "
    "class recording. Turn it into clean, well-structured notes.\n\n"
    "Strict rules:\n"
    "- Only include what was actually said in the transcript below.\n"
    "- Never use your own outside knowledge to add explanations, definitions, "
    "or details the transcript doesn't contain — even for topics you "
    "recognize and know more about.\n"
    "- If a topic is only mentioned briefly, the corresponding notes must "
    "stay equally brief. Do not expand a one-sentence mention into a "
    "multi-paragraph explanation.\n"
    "- If the transcript is too short or unclear to produce meaningful "
    "notes, say so plainly instead of inventing content.\n\n"
    "Organize the material under clear headings only where there's enough "
    "real content to justify structure; use plain, concise language.\n"
    "------\n"
    "Transcript:\n{transcript}\n"
    "------\n"
    "Structured notes:\n"
)

# In-memory, used only for sessions actively recording/processing in this
# process's lifetime — list_sessions/get_session_detail fall back to disk
# for anything else (including every session from a previous app run).
_SESSIONS: dict[str, dict] = {}


def _sessions_dir(ssb_home: Path, course_id: int) -> Path:
    return ssb_home / "courses" / str(course_id) / "sessions"


def _session_dir(ssb_home: Path, course_id: int, session_id: str) -> Path:
    return _sessions_dir(ssb_home, course_id) / session_id


def _read_meta(session_dir: Path) -> dict:
    meta_path = session_dir / "meta.json"
    return json.loads(meta_path.read_text()) if meta_path.exists() else {}


def _write_meta(session_dir: Path, meta: dict) -> None:
    (session_dir / "meta.json").write_text(json.dumps(meta))


def start_session(ssb_home: Path, course_id: int) -> dict:
    sessions_dir = _sessions_dir(ssb_home, course_id)
    sessions_dir.mkdir(parents=True, exist_ok=True)
    class_num = len([p for p in sessions_dir.iterdir() if p.is_dir()]) + 1
    session_id = f"{date.today().isoformat()}-class-{class_num}"
    session_dir = sessions_dir / session_id
    session_dir.mkdir(exist_ok=True)
    title = f"Class #{class_num} — {date.today().isoformat()}"
    _write_meta(session_dir, {"title": title})
    _SESSIONS[session_id] = {
        "status": "recording",
        "course_id": course_id,
        "dir": session_dir,
        "class_num": class_num,
        "source_label": title,
    }
    return {"session_id": session_id, "status": "recording"}


def save_notes(session_id: str, text: str) -> None:
    info = _SESSIONS[session_id]
    (info["dir"] / "notes.md").write_text(text)


def stop_session(session_id: str, audio_bytes: bytes, db_path: Path) -> dict:
    info = _SESSIONS[session_id]
    audio_path = info["dir"] / "audio.m4a"
    audio_path.write_bytes(audio_bytes)
    info["status"] = "processing"
    threading.Thread(target=_process_session, args=(session_id, audio_path, db_path), daemon=True).start()
    return {"session_id": session_id, "status": "processing"}


def _process_session(session_id: str, audio_path: Path, db_path: Path) -> None:
    info = _SESSIONS[session_id]
    try:
        raw_segments, _ = _get_model().transcribe(str(audio_path))
        segments = [{"start": s.start, "end": s.end, "text": s.text} for s in raw_segments]
        transcript_text = " ".join(s["text"].strip() for s in segments).strip()
        (info["dir"] / "transcript.json").write_text(json.dumps(segments, indent=2))

        audio_path.unlink(missing_ok=True)  # data-model.md §1 — raw audio not kept

        summary = _enhance_notes(transcript_text) if transcript_text else ""
        (info["dir"] / "summary.md").write_text(summary)

        source_label = info["source_label"]
        nodes = indexing.transcript_to_nodes(segments, source_label, session_id)
        notes_path = info["dir"] / "notes.md"
        if notes_path.exists():
            nodes += indexing.notes_to_nodes(notes_path.read_text(), source_label, session_id)
        if nodes:
            indexing.add_nodes(nodes, db_path, f"course_{info['course_id']}")

        info["status"] = "done"
        info["transcript"] = transcript_text
        info["summary"] = summary
    except Exception as e:
        # Real finding: this used to fail silently — status flipped to
        # "error" in the in-memory dict with nothing printed anywhere, so a
        # real failure here was undiagnosable from the sidecar's own output.
        traceback.print_exc()
        info["status"] = "error"
        info["error"] = str(e)


def _enhance_notes(transcript_text: str) -> str:
    llm = OpenAI(model=generation.DEFAULT_MODEL, api_key=generation._get_llm_key())
    return str(llm.complete(SUMMARY_TEMPLATE.format(transcript=transcript_text)))


def _status_from_disk(session_dir: Path) -> str:
    if (session_dir / "summary.md").exists():
        return "done"
    # A session directory with no summary.md and not actively tracked in
    # _SESSIONS is either from a run that errored, or one abandoned
    # mid-recording (app closed before stop) — both look the same from
    # disk alone, and both are dead ends the student can only delete.
    return "error"


def list_sessions(ssb_home: Path, course_id: int) -> list[dict]:
    sessions_dir = _sessions_dir(ssb_home, course_id)
    if not sessions_dir.exists():
        return []
    result = []
    for session_dir in sorted((p for p in sessions_dir.iterdir() if p.is_dir()), reverse=True):
        session_id = session_dir.name
        meta = _read_meta(session_dir)
        live = _SESSIONS.get(session_id)
        status = live["status"] if live and live["course_id"] == course_id else _status_from_disk(session_dir)
        result.append({"session_id": session_id, "title": meta.get("title", session_id), "status": status})
    return result


def get_session_detail(ssb_home: Path, course_id: int, session_id: str) -> dict | None:
    session_dir = _session_dir(ssb_home, course_id, session_id)
    if not session_dir.exists():
        return None
    meta = _read_meta(session_dir)
    live = _SESSIONS.get(session_id)
    status = live["status"] if live and live["course_id"] == course_id else _status_from_disk(session_dir)
    detail: dict = {"session_id": session_id, "title": meta.get("title", session_id), "status": status}
    if live and "error" in live:
        detail["error"] = live["error"]
    transcript_path = session_dir / "transcript.json"
    if transcript_path.exists():
        segments = json.loads(transcript_path.read_text())
        detail["transcript"] = " ".join(s["text"].strip() for s in segments)
    summary_path = session_dir / "summary.md"
    if summary_path.exists():
        detail["summary"] = summary_path.read_text()
    notes_path = session_dir / "notes.md"
    if notes_path.exists():
        detail["notes"] = notes_path.read_text()
    return detail


def rename_session(ssb_home: Path, course_id: int, session_id: str, title: str) -> None:
    session_dir = _session_dir(ssb_home, course_id, session_id)
    if not session_dir.exists():
        raise KeyError(session_id)
    meta = _read_meta(session_dir)
    meta["title"] = title
    _write_meta(session_dir, meta)
    if session_id in _SESSIONS:
        _SESSIONS[session_id]["source_label"] = title


def delete_session(ssb_home: Path, course_id: int, session_id: str, db_path: Path) -> None:
    session_dir = _session_dir(ssb_home, course_id, session_id)
    if not session_dir.exists():
        raise KeyError(session_id)
    shutil.rmtree(session_dir)
    _SESSIONS.pop(session_id, None)
    indexing.delete_ref_doc_nodes(db_path, f"course_{course_id}", session_id)
