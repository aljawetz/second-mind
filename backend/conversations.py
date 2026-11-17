"""Saved course chats — docs/superpowers/plans/2026-09-23-conversation-history.md.

One JSON file per conversation, under the course directory, so removing a
course (courses.delete_course) takes its conversations with it:

    ~/.secondmind/courses/{course_id}/conversations/{conversation_id}.json

Each file also carries what agent memory needs to pick up where it left off
(docs/superpowers/specs/2026-09-25-agent-memory-design.md §5.1, §5.6):
`memory_processed_upto`, the number of turns memory has already read,
`turns_indexed_upto`, the number already in the past-chat index (absent in
files saved before it existed), and `summary`, the conversation's running
summary.
"""

import json
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

TITLE_CHARS = 60

# One lock for every read-modify-write below: ThreadingHTTPServer can run
# two /ask requests for one conversation at once, and the memory worker
# writes its progress while /ask appends. Same reasoning as
# sessions._counter_lock.
_lock = threading.Lock()


def new_conversation_id() -> str:
    # Matches main.py's [\w-]+ route pattern, which also rules out path traversal.
    return "c-" + uuid.uuid4().hex[:12]


def _dir(sm_home: Path, course_id: int) -> Path:
    return sm_home / "courses" / str(course_id) / "conversations"


def _path(sm_home: Path, course_id: int, cid: str) -> Path:
    return _dir(sm_home, course_id) / f"{cid}.json"


def _write(path: Path, data: dict) -> None:
    # Through a temp file, so a crash mid-write can't leave half a JSON file.
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    os.replace(tmp, path)


def exists(sm_home: Path, course_id: int, cid: str) -> bool:
    return _path(sm_home, course_id, cid).exists()


def append_turn(sm_home: Path, course_id: int, cid: str, turn: dict, *, create_if_missing: bool = True) -> int | None:
    """turn: {question, answer, citations, grounded, asked_at}, plus
    memory_ids when the answer drew on agent memory. The first
    turn creates the conversation, titled by its question.

    When create_if_missing is False, a missing file means the chat was deleted
    mid-request and the turn is dropped (same rule as set_memory_progress).
    Returns the saved zero-based index, or None when dropped."""
    path = _path(sm_home, course_id, cid)
    with _lock:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
        elif not create_if_missing:
            return None
        else:
            data = {
                "conversation_id": cid,
                "title": " ".join(turn["question"].split())[:TITLE_CHARS],
                "created_at": turn["asked_at"],
                "memory_processed_upto": 0,
                "turns_indexed_upto": 0,
                "summary": "",
                "turns": [],
            }
        turn_index = len(data["turns"])
        data["turns"].append(turn)
        data["updated_at"] = turn["asked_at"]
        _write(path, data)
    return turn_index


def set_feedback(
    sm_home: Path, course_id: int, cid: str, turn_index: int,
    rating: str | None, note: str = "",
) -> dict | None:
    """Replace or clear a saved turn's feedback without changing chat recency.

    Missing chats/turns raise KeyError; invalid feedback raises ValueError.
    Shares the append/memory lock so none of those writes lose one another.
    """
    if rating not in ("up", "down", None):
        raise ValueError("rating must be up, down, or null")
    if not isinstance(note, str) or len(note) > 500:
        raise ValueError("note must be a string of at most 500 characters")
    path = _path(sm_home, course_id, cid)
    with _lock:
        if not path.exists():
            raise KeyError(cid)
        data = json.loads(path.read_text(encoding="utf-8"))
        if not 0 <= turn_index < len(data["turns"]):
            raise KeyError(turn_index)
        turn = data["turns"][turn_index]
        feedback = None
        if rating is None:
            turn.pop("feedback", None)
        else:
            feedback = {
                "rating": rating,
                "note": note,
                "updated_at": datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z"),
            }
            turn["feedback"] = feedback
        _write(path, data)
    return feedback


def list_feedback(sm_home: Path, course_id: int) -> list[dict]:
    """Thumbs-down turns for local review, newest feedback first."""
    turns = []
    with _lock:
        for path in _dir(sm_home, course_id).glob("*.json"):
            data = json.loads(path.read_text(encoding="utf-8"))
            for turn_index, turn in enumerate(data["turns"]):
                if (turn.get("feedback") or {}).get("rating") == "down":
                    turns.append({
                        **turn,
                        "conversation_id": data["conversation_id"],
                        "title": data["title"],
                        "turn_index": turn_index,
                    })
    return sorted(turns, key=lambda t: t["feedback"]["updated_at"], reverse=True)


def get_conversation(sm_home: Path, course_id: int, cid: str) -> dict | None:
    path = _path(sm_home, course_id, cid)
    with _lock:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def list_conversations(sm_home: Path, course_id: int) -> list[dict]:
    directory = _dir(sm_home, course_id)
    if not directory.exists():
        return []
    summaries = []
    with _lock:
        for path in directory.glob("*.json"):
            data = json.loads(path.read_text(encoding="utf-8"))
            summaries.append(
                {
                    "conversation_id": data["conversation_id"],
                    "title": data["title"],
                    "updated_at": data["updated_at"],
                    "turn_count": len(data["turns"]),
                }
            )
    return sorted(summaries, key=lambda s: s["updated_at"], reverse=True)


def delete_conversation(sm_home: Path, course_id: int, cid: str) -> None:
    """Raises KeyError if missing, same contract as sessions.delete_session."""
    path = _path(sm_home, course_id, cid)
    with _lock:
        if not path.exists():
            raise KeyError(cid)
        path.unlink()


def set_memory_progress(sm_home: Path, course_id: int, cid: str, *, processed_upto: int, summary: str) -> None:
    """The memory worker has read the first `processed_upto` turns. A
    conversation deleted meanwhile stays deleted."""
    path = _path(sm_home, course_id, cid)
    with _lock:
        if not path.exists():
            return
        data = json.loads(path.read_text(encoding="utf-8"))
        data["memory_processed_upto"] = processed_upto
        data["summary"] = summary
        _write(path, data)


def set_turns_indexed(sm_home: Path, course_id: int, cid: str, upto: int) -> None:
    """The first `upto` turns are in the past-chat index (memory/past_chats.py),
    or were passed over for good. A conversation deleted meanwhile stays deleted."""
    path = _path(sm_home, course_id, cid)
    with _lock:
        if not path.exists():
            return
        data = json.loads(path.read_text(encoding="utf-8"))
        data["turns_indexed_upto"] = upto
        _write(path, data)


def clear_summaries(sm_home: Path, course_id: int, cids: list[str]) -> None:
    """Something these chats told memory was forgotten, and their running
    summaries may repeat it. Cleared, not rewritten: the next turn starts a
    new summary, and chat sends the plain recent turns until then."""
    with _lock:
        for cid in cids:
            path = _path(sm_home, course_id, cid)
            if not path.exists():
                continue
            data = json.loads(path.read_text(encoding="utf-8"))
            data["summary"] = ""
            _write(path, data)


def pending_memory(sm_home: Path, course_id: int) -> list[str]:
    """Conversations with turns memory hasn't read yet, or not yet in the
    past-chat index: what the worker picks up again after a restart. A chat
    saved before that index existed has no counter, so all of it is pending."""
    directory = _dir(sm_home, course_id)
    if not directory.exists():
        return []
    pending = []
    with _lock:
        for path in sorted(directory.glob("*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            turns = len(data["turns"])
            if data["memory_processed_upto"] < turns or data.get("turns_indexed_upto", 0) < turns:
                pending.append(data["conversation_id"])
    return pending
