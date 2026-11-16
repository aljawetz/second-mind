"""sync_jobs: syncs started from Claude Code run in the background, report
progress through a status file every session can read, and never run twice
at once for one course."""

import json
import subprocess
import sys
import threading
from pathlib import Path

import pytest

import mcp_server
import sync_jobs

COURSE = 55016


def _events(*items, done=None):
    def run(course_id, home):
        yield from items
        yield done or {"done": True, "new": 2, "changed": 0, "removed": 0, "failed": 1}

    return run


def test_a_sync_reports_counts_and_its_summary(tmp_path):
    finished = []
    jobs = sync_jobs.SyncJobs(
        tmp_path,
        run=_events({"item": "a.pdf", "status": "done"}, {"item": "b.pdf", "status": "done"},
                    {"item": "c.pdf", "status": "failed", "error": "403"}),
        ensure_model=lambda: None,
        on_done=finished.append,
    )

    started = jobs.start(COURSE, wait=True)

    status = sync_jobs.read_status(tmp_path, COURSE)
    assert started["started"] is True
    assert status["state"] == "done"
    assert (status["items_done"], status["items_failed"]) == (2, 1)
    assert status["summary"] == {"new": 2, "changed": 0, "removed": 0, "failed": 1}
    assert status["finished_at"] and "phase" not in status
    assert finished == [COURSE]  # the server drops its cached retriever here


def test_a_course_sync_error_is_a_failed_sync(tmp_path):
    jobs = sync_jobs.SyncJobs(tmp_path, run=_events(done={"done": True, "error": "401 Unauthorized"}),
                              ensure_model=lambda: None)

    jobs.start(COURSE, wait=True)

    status = sync_jobs.read_status(tmp_path, COURSE)
    assert (status["state"], status["error"]) == ("failed", "401 Unauthorized")


def test_a_failed_model_download_fails_the_sync_and_frees_the_course(tmp_path):
    def no_network():
        raise RuntimeError("Could not download model.onnx from Hugging Face")

    jobs = sync_jobs.SyncJobs(tmp_path, run=_events(), ensure_model=no_network)

    jobs.start(COURSE, wait=True)

    status = sync_jobs.read_status(tmp_path, COURSE)
    assert status["state"] == "failed" and "Hugging Face" in status["error"]
    assert jobs.start(COURSE, wait=True)["started"] is True


def test_a_second_start_while_running_does_not_start_another(tmp_path):
    release, entered = threading.Event(), threading.Event()

    def slow(course_id, home):
        entered.set()
        release.wait(5)
        yield {"done": True, "new": 0, "changed": 0, "removed": 0, "failed": 0}

    jobs = sync_jobs.SyncJobs(tmp_path, run=slow, ensure_model=lambda: None)
    assert jobs.start(COURSE)["started"] is True
    entered.wait(5)

    again = jobs.start(COURSE)

    assert again["started"] is False and again["state"] == "running"
    release.set()
    jobs._threads[COURSE].join(5)
    assert sync_jobs.read_status(tmp_path, COURSE)["state"] == "done"


def test_another_process_holding_the_lock_blocks_a_start(tmp_path):
    lock = tmp_path / "courses" / str(COURSE) / sync_jobs.LOCK_FILE
    lock.parent.mkdir(parents=True)
    holder = subprocess.Popen(
        [sys.executable, "-c",
         f"import fcntl,sys,time; f=open({str(lock)!r},'a+'); fcntl.flock(f, fcntl.LOCK_EX); print('locked', flush=True); time.sleep(30)"],
        stdout=subprocess.PIPE, text=True,
    )
    try:
        assert holder.stdout.readline().strip() == "locked"
        jobs = sync_jobs.SyncJobs(tmp_path, run=lambda *a: pytest.fail("must not run"), ensure_model=lambda: None)

        assert jobs.start(COURSE, wait=True)["started"] is False
    finally:
        holder.kill()


def test_running_with_nobody_holding_the_lock_reads_as_interrupted(tmp_path):
    course_dir = tmp_path / "courses" / str(COURSE)
    course_dir.mkdir(parents=True)
    (course_dir / sync_jobs.STATUS_FILE).write_text(json.dumps({"course_id": COURSE, "state": "running"}))

    status = sync_jobs.read_status(tmp_path, COURSE)

    assert status["state"] == "interrupted"
    assert "sync_course again" in status["note"]


# --- the tools ---------------------------------------------------------------


def test_sync_course_without_a_token_says_how_to_fix_it(tmp_path):
    def no_token():
        raise mcp_server.canvas.CanvasError("no token")

    jobs = sync_jobs.SyncJobs(tmp_path, run=lambda *a: pytest.fail("must not run"), ensure_model=lambda: None)

    out = mcp_server.sync_course_result(jobs, COURSE, token_check=no_token)

    assert out == {"course_id": COURSE, "started": False, "error": "No Canvas token is set up"}


def test_sync_status_for_one_course_or_all(tmp_path):
    jobs = sync_jobs.SyncJobs(tmp_path, run=_events(), ensure_model=lambda: None)
    jobs.start(COURSE, wait=True)
    jobs.start(56350, wait=True)

    assert [s["course_id"] for s in mcp_server.sync_status_result(tmp_path, None)["syncs"]] == [COURSE, 56350]
    assert mcp_server.sync_status_result(tmp_path, COURSE)["syncs"][0]["state"] == "done"
    assert "never been synced" in mcp_server.sync_status_result(tmp_path, 1)["note"]
