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
"""

import json
import threading
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


SUMMARY_TEMPLATE = PromptTemplate(
    "You are SSB, a study assistant. The following is a raw transcript of a "
    "class recording. Turn it into clean, well-structured notes: organize "
    "the material under clear headings, capture the key concepts and any "
    "examples discussed, and use plain, concise language. Do not add "
    "information that isn't in the transcript.\n"
    "------\n"
    "Transcript:\n{transcript}\n"
    "------\n"
    "Structured notes:\n"
)

# In-memory only — fine for a single-process sidecar. A session still
# "processing" when the app quits isn't recovered on the next launch; same
# category of accepted limitation as sync's eventual consistency (§5.5).
_SESSIONS: dict[str, dict] = {}


def _sessions_dir(ssb_home: Path, course_id: int) -> Path:
    return ssb_home / "courses" / str(course_id) / "sessions"


def start_session(ssb_home: Path, course_id: int) -> dict:
    sessions_dir = _sessions_dir(ssb_home, course_id)
    sessions_dir.mkdir(parents=True, exist_ok=True)
    class_num = len([p for p in sessions_dir.iterdir() if p.is_dir()]) + 1
    session_id = f"{date.today().isoformat()}-class-{class_num}"
    session_dir = sessions_dir / session_id
    session_dir.mkdir(exist_ok=True)
    _SESSIONS[session_id] = {
        "status": "recording",
        "course_id": course_id,
        "dir": session_dir,
        "class_num": class_num,
        "source_label": f"Class #{class_num} — {date.today().isoformat()}",
    }
    return {"session_id": session_id, "status": "recording"}


def save_notes(session_id: str, text: str) -> None:
    info = _SESSIONS[session_id]
    (info["dir"] / "notes.md").write_text(text)


def get_status(session_id: str) -> dict | None:
    info = _SESSIONS.get(session_id)
    if info is None:
        return None
    return {k: v for k, v in info.items() if k != "dir"}


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
        info["status"] = "error"
        info["error"] = str(e)


def _enhance_notes(transcript_text: str) -> str:
    llm = OpenAI(model=generation.DEFAULT_MODEL, api_key=generation._get_llm_key())
    return str(llm.complete(SUMMARY_TEMPLATE.format(transcript=transcript_text)))
