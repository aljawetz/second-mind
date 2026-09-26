"""Saved course chats — docs/superpowers/plans/2026-09-23-conversation-history.md.

One JSON file per conversation, under the course directory, so removing a
course (courses.delete_course) takes its conversations with it:

    ~/.secondmind/courses/{course_id}/conversations/{conversation_id}.json

Each file also carries what agent memory needs to pick up where it left off
(docs/superpowers/specs/2026-09-25-agent-memory-design.md §5.1, §5.6):
`memory_processed_upto`, the number of turns memory has already read, and
`summary`, the conversation's running summary.
"""

import json
import os
import threading
import uuid
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
    tmp.write_text(json.dumps(data))
    os.replace(tmp, path)


def exists(sm_home: Path, course_id: int, cid: str) -> bool:
    return _path(sm_home, course_id, cid).exists()


def append_turn(sm_home: Path, course_id: int, cid: str, turn: dict) -> None:
    """turn: {question, answer, citations, grounded, asked_at}. The first
    turn creates the conversation, titled by its question."""
    path = _path(sm_home, course_id, cid)
    with _lock:
        if path.exists():
            data = json.loads(path.read_text())
        else:
            data = {
                "conversation_id": cid,
                "title": " ".join(turn["question"].split())[:TITLE_CHARS],
                "created_at": turn["asked_at"],
                "memory_processed_upto": 0,
                "summary": "",
                "turns": [],
            }
        data["turns"].append(turn)
        data["updated_at"] = turn["asked_at"]
        _write(path, data)


def get_conversation(sm_home: Path, course_id: int, cid: str) -> dict | None:
    path = _path(sm_home, course_id, cid)
    with _lock:
        return json.loads(path.read_text()) if path.exists() else None


def list_conversations(sm_home: Path, course_id: int) -> list[dict]:
    directory = _dir(sm_home, course_id)
    if not directory.exists():
        return []
    summaries = []
    with _lock:
        for path in directory.glob("*.json"):
            data = json.loads(path.read_text())
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
        data = json.loads(path.read_text())
        data["memory_processed_upto"] = processed_upto
        data["summary"] = summary
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
            data = json.loads(path.read_text())
            data["summary"] = ""
            _write(path, data)


def pending_memory(sm_home: Path, course_id: int) -> list[str]:
    """Conversations with turns memory hasn't read yet: what the worker
    picks up again after a restart."""
    directory = _dir(sm_home, course_id)
    if not directory.exists():
        return []
    pending = []
    with _lock:
        for path in sorted(directory.glob("*.json")):
            data = json.loads(path.read_text())
            if data["memory_processed_upto"] < len(data["turns"]):
                pending.append(data["conversation_id"])
    return pending
