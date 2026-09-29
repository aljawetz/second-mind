"""main.py process lifecycle — runs the real backend as a subprocess.

Guards the orphaned-sidecar bug: the backend outlived the Tauri app, kept
port 8756, and the next launch silently talked to the stale process. Each
test gets its own free port via SM_PORT so it never collides with a
running Second Mind.
"""

import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
STARTUP_TIMEOUT = 90  # main.py imports llama_index/lancedb/onnxruntime up front
EXIT_TIMEOUT = 10


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _spawn(port: int, *, pending_stdout: bool = False, **extra_env) -> subprocess.Popen:
    env = {**os.environ, "SM_PORT": str(port), "SM_INSTANCE_TOKEN": "test-token", **extra_env}
    argv = [sys.executable, "main.py"]
    if pending_stdout:
        # Leaves unflushed bytes in main.py's block-buffered stdout pipe
        # before it starts serving — what course_sync's print() does during
        # the launch-time sync in the real app.
        argv = [
            sys.executable,
            "-c",
            "import runpy, sys; print('buffered, not flushed'); sys.argv = ['main.py']; "
            "runpy.run_path('main.py', run_name='__main__')",
        ]
    return subprocess.Popen(
        argv,
        cwd=BACKEND_DIR,
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE if pending_stdout else subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )


def _wait_for_ping(proc: subprocess.Popen, port: int) -> dict:
    deadline = time.monotonic() + STARTUP_TIMEOUT
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            pytest.fail(f"backend exited early ({proc.returncode}): {proc.stderr.read().decode()}")
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/ping", timeout=1) as res:
                return json.loads(res.read())
        except OSError:
            time.sleep(0.3)
    pytest.fail("backend never answered /ping")


@pytest.fixture
def backend():
    procs = []

    def start(port, **kwargs):
        proc = _spawn(port, **kwargs)
        procs.append(proc)
        return proc

    yield start
    for proc in procs:
        if proc.poll() is None:
            proc.kill()
            proc.wait()


def test_ping_reports_the_instance_token_it_was_launched_with(backend):
    port = _free_port()
    proc = backend(port)
    assert _wait_for_ping(proc, port) == {"status": "ok", "source": "sm-backend", "instance": "test-token"}


def test_exits_cleanly_when_the_app_closes_its_stdin(backend):
    port = _free_port()
    proc = backend(port, SM_EXIT_ON_STDIN_EOF="1")
    _wait_for_ping(proc, port)

    proc.stdin.close()  # what happens when the Tauri process ends, however it ends

    assert proc.wait(timeout=EXIT_TIMEOUT) == 0
    assert b"mutex" not in proc.stderr.read()


def test_exits_when_the_app_dies_with_unflushed_stdout(backend):
    # The real failure: the Tauri process ends, closing our stdin AND the
    # stdout/stderr pipes it was reading. Flushing buffered stdout into the
    # dead pipe raised BrokenPipeError before os._exit ran, killing only the
    # watchdog thread and leaving the backend serving forever.
    port = _free_port()
    proc = backend(port, pending_stdout=True, SM_EXIT_ON_STDIN_EOF="1")
    _wait_for_ping(proc, port)

    proc.stdout.close()
    proc.stderr.close()
    proc.stdin.close()

    assert proc.wait(timeout=EXIT_TIMEOUT) == 0


def test_stdin_eof_is_ignored_without_the_opt_in_flag(backend):
    # Running main.py by hand (or under a tool that gives it /dev/null) must
    # not make it exit immediately — only the Tauri launch opts in.
    port = _free_port()
    proc = backend(port)
    _wait_for_ping(proc, port)

    proc.stdin.close()
    time.sleep(2)

    assert proc.poll() is None
    assert _wait_for_ping(proc, port)["status"] == "ok"


@pytest.mark.skipif(sys.platform == "win32", reason="send_signal(SIGTERM) is TerminateProcess on Windows, so there is no graceful exit to assert")
def test_sigterm_exits_cleanly(backend):
    port = _free_port()
    proc = backend(port)
    _wait_for_ping(proc, port)

    proc.send_signal(signal.SIGTERM)

    assert proc.wait(timeout=EXIT_TIMEOUT) == 0


def test_port_in_use_exits_with_a_readable_message(backend):
    port = _free_port()
    with socket.socket() as squatter:
        squatter.bind(("127.0.0.1", port))
        squatter.listen()

        proc = backend(port)
        code = proc.wait(timeout=STARTUP_TIMEOUT)

    stderr = proc.stderr.read().decode()
    assert code == 1
    assert f"port {port} is already in use" in stderr
    assert "Traceback" not in stderr

