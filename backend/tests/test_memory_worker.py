"""memory.worker.MemoryWorker — the background thread memory writes run on
(design spec §5.1): after an answer has streamed, never in its way."""

import threading
import time

from memory.worker import MemoryWorker


def test_submit_returns_before_the_job_runs():
    release = threading.Event()
    ran = []
    worker = MemoryWorker(lambda job: (release.wait(5), ran.append(job)))

    worker.submit("a")
    assert ran == []  # still waiting on release: submit didn't wait for it

    release.set()
    assert worker.wait_idle(5)
    assert ran == ["a"]


def test_jobs_run_in_order_one_at_a_time():
    running, most_at_once, ran = [0], [0], []
    lock = threading.Lock()

    def run(job):
        with lock:
            running[0] += 1
            most_at_once[0] = max(most_at_once[0], running[0])
        time.sleep(0.01)
        ran.append(job)
        with lock:
            running[0] -= 1

    worker = MemoryWorker(run)
    for job in range(8):
        worker.submit(job)

    assert worker.wait_idle(5)
    assert ran == list(range(8))
    assert most_at_once[0] == 1


def test_a_failing_job_is_logged_and_the_next_one_still_runs():
    logged, ran = [], []

    def run(job):
        if job == "bad":
            raise RuntimeError("no OpenAI key stored")
        ran.append(job)

    worker = MemoryWorker(run, log=logged.append)
    worker.submit("bad")
    worker.submit("good")

    assert worker.wait_idle(5)
    assert ran == ["good"]
    assert len(logged) == 1 and "bad" in logged[0] and "no OpenAI key stored" in logged[0]


def test_a_job_already_waiting_is_not_queued_twice():
    # Two quick questions in one chat each queue that chat; the job reads
    # every turn not yet read, so the second copy would find nothing.
    release = threading.Event()
    ran = []
    worker = MemoryWorker(lambda job: (release.wait(5) if job == "first" else None, ran.append(job)))

    worker.submit("first")  # running, blocked
    worker.submit("chat-1")
    worker.submit("chat-1")
    release.set()

    assert worker.wait_idle(5)
    assert ran == ["first", "chat-1"]


def test_a_job_can_be_queued_again_once_it_has_started():
    # A turn saved while its chat's job is already running must still be read.
    started, release = threading.Event(), threading.Event()
    ran = []

    def run(job):
        if not ran:
            started.set()
            release.wait(5)
        ran.append(job)

    worker = MemoryWorker(run)
    worker.submit("chat-1")
    assert started.wait(5)
    worker.submit("chat-1")
    release.set()

    assert worker.wait_idle(5)
    assert ran == ["chat-1", "chat-1"]
