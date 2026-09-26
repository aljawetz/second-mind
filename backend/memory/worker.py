"""The background thread memory writes run on — design spec §5.1.

/ask queues a job once its answer has streamed, so extraction and
consolidation (one or two model calls) never delay an answer, and a failed
job can't break one. One thread: memory writes happen one at a time (no two
consolidations racing on the same memories), and model spend stays bounded.
"""

import queue
import sys
import threading
import time
import traceback
from typing import Callable, Hashable


def _stderr(message: str) -> None:
    print(message, file=sys.stderr)


class MemoryWorker:
    """Runs run(job) for each submitted job, in order, on one daemon thread.
    Jobs are hashable keys (the app uses (course_id, conversation_id)); a
    job already waiting isn't queued again, since it will read every turn
    not yet read anyway."""

    def __init__(self, run: Callable[[Hashable], None], log: Callable[[str], None] = _stderr):
        self._run = run
        self._log = log
        self._queue: queue.Queue = queue.Queue()
        self._waiting: set = set()
        self._lock = threading.Lock()
        threading.Thread(target=self._loop, name="memory-worker", daemon=True).start()

    def submit(self, job: Hashable) -> None:
        with self._lock:
            if job in self._waiting:
                return
            self._waiting.add(job)
        self._queue.put(job)

    def wait_idle(self, timeout: float | None = None) -> bool:
        """Blocks until every submitted job has finished. False on timeout.
        For tests and the evaluation; the app never waits."""
        deadline = None if timeout is None else time.monotonic() + timeout
        with self._queue.all_tasks_done:
            while self._queue.unfinished_tasks:
                remaining = None if deadline is None else deadline - time.monotonic()
                if remaining is not None and remaining <= 0:
                    return False
                self._queue.all_tasks_done.wait(remaining)
        return True

    def _loop(self) -> None:
        while True:
            job = self._queue.get()
            # No longer waiting once started: a turn saved while this job
            # runs must queue the job again, or it would go unread.
            with self._lock:
                self._waiting.discard(job)
            try:
                self._run(job)
            except Exception:
                self._log(f"memory job {job!r} failed:\n{traceback.format_exc()}")
            finally:
                self._queue.task_done()
