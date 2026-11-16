"""Course syncs started from Claude Code (plan
docs/plans/2026-11-13-claude-code-plugin.md: everything happens inside the
plugin, the student runs nothing else).

A sync takes minutes, longer than a tool call should block, so sync_course
starts it on a thread and returns; sync_status reads how far it got. The
state lives in a file next to the course's manifest, not in memory, so every
Claude Code session sees the same sync. A lock file held for the whole run
keeps two sessions from syncing one course at once; a status that says
"running" while nobody holds the lock is a sync whose session closed, and it
reads as "interrupted" (sync is incremental, so running it again resumes).
"""

import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

logger = logging.getLogger("sm-mcp.sync")

STATUS_FILE = "sync_status.json"
LOCK_FILE = "sync.lock"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _course_dir(home: Path, course_id: int) -> Path:
    return home / "courses" / str(course_id)


class _Lock:
    """An exclusive, non-blocking lock on a file, released when the process
    dies, so a crashed sync never leaves a course locked."""

    def __init__(self, path: Path):
        self._path = path
        self._file = None

    def acquire(self) -> bool:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        f = open(self._path, "a+")
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            f.close()
            return False
        self._file = f
        return True

    def release(self) -> None:
        if self._file:
            self._file.close()  # closing drops the lock on every platform
            self._file = None


def _locked(home: Path, course_id: int) -> bool:
    probe = _Lock(_course_dir(home, course_id) / LOCK_FILE)
    if probe.acquire():
        probe.release()
        return False
    return True


def read_status(home: Path, course_id: int) -> dict | None:
    path = _course_dir(home, course_id) / STATUS_FILE
    try:
        status = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    if status.get("state") == "running" and not _locked(home, course_id):
        status["state"] = "interrupted"
        status["note"] = "The session running this sync closed before it finished. Run sync_course again to resume."
    return status


def _write_status(home: Path, course_id: int, status: dict) -> None:
    path = _course_dir(home, course_id) / STATUS_FILE
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(status))
    tmp.replace(path)


class SyncJobs:
    def __init__(self, home: Path, run: Callable | None = None, ensure_model: Callable | None = None,
                 on_done: Callable[[int], None] | None = None):
        self._home = home
        self._run = run
        self._ensure_model = ensure_model
        self._on_done = on_done or (lambda _cid: None)
        self._threads: dict[int, threading.Thread] = {}

    def start(self, course_id: int, wait: bool = False) -> dict:
        """Starts a sync of one course unless one is already running (here
        or in another session). wait=True runs it on this thread (tests)."""
        lock = _Lock(_course_dir(self._home, course_id) / LOCK_FILE)
        if not lock.acquire():
            return {"course_id": course_id, "started": False, **(read_status(self._home, course_id) or {"state": "running"})}
        status = {"course_id": course_id, "state": "running", "phase": "starting", "started_at": _now(),
                  "items_done": 0, "items_failed": 0}
        _write_status(self._home, course_id, status)
        if wait:
            self._job(course_id, lock, status)
        else:
            thread = threading.Thread(target=self._job, args=(course_id, lock, status), daemon=True,
                                      name=f"sync-{course_id}")
            self._threads[course_id] = thread
            thread.start()
        return {"course_id": course_id, "started": True, **read_status(self._home, course_id)}

    def _job(self, course_id: int, lock: _Lock, status: dict) -> None:
        def update(**fields):
            status.update(fields)
            _write_status(self._home, course_id, status)

        try:
            update(phase="downloading the search model (first sync only)")
            (self._ensure_model or _default_ensure_model)()
            update(phase="reading the course from Canvas and indexing it")
            for event in (self._run or _default_run)(course_id, self._home):
                if event.get("done"):
                    if event.get("error"):
                        update(state="failed", error=event["error"])
                    else:
                        summary = {k: event.get(k, 0) for k in ("new", "changed", "removed", "failed")}
                        update(state="done", summary=summary)
                    break
                if event.get("status") == "failed":
                    update(items_failed=status["items_failed"] + 1, last_item=event.get("item"))
                else:
                    update(items_done=status["items_done"] + 1, last_item=event.get("item"))
            else:
                update(state="failed", error="The sync stopped without finishing.")
        except Exception as e:  # anything at all: the status must never stay "running"
            logger.exception("sync of course %s failed", course_id)
            update(state="failed", error=str(e))
        finally:
            status.pop("phase", None)
            update(finished_at=_now())
            lock.release()
            self._on_done(course_id)


def _default_ensure_model():
    import model_download

    model_download.ensure_embedding_model()


def _default_run(course_id: int, home: Path):
    import course_sync

    return course_sync.sync_course(course_id, home)
