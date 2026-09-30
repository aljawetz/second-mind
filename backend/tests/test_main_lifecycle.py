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
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

BACKEND_DIR = Path(__file__).resolve().parent.parent
STARTUP_TIMEOUT = 90
EXIT_TIMEOUT = 10
# CI guardrail after lazy imports + background startup jobs in main.py.
PING_STARTUP_BUDGET = 15


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


def _stop(proc: subprocess.Popen) -> None:
    if proc.poll() is None:
        proc.kill()
    proc.wait()


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


@dataclass(frozen=True)
class _WarmScenario:
    test_name: str
    extra_env: dict = field(default_factory=dict)
    pending_stdout: bool = False


_WARM_SCENARIOS = (
    _WarmScenario("test_ping_reports_the_instance_token_it_was_launched_with"),
    _WarmScenario("test_exits_cleanly_when_the_app_closes_its_stdin", {"SM_EXIT_ON_STDIN_EOF": "1"}),
    _WarmScenario(
        "test_exits_when_the_app_dies_with_unflushed_stdout",
        {"SM_EXIT_ON_STDIN_EOF": "1"},
        pending_stdout=True,
    ),
    _WarmScenario("test_stdin_eof_is_ignored_without_the_opt_in_flag"),
    _WarmScenario("test_sigterm_exits_cleanly"),
)


def _warm_one(sm_home: Path, scenario: _WarmScenario) -> tuple[str, subprocess.Popen, int, dict]:
    port = _free_port()
    env = {"SM_HOME": str(sm_home), **scenario.extra_env}
    proc = _spawn(port, pending_stdout=scenario.pending_stdout, **env)
    ping = _wait_for_ping(proc, port)
    return scenario.test_name, proc, port, ping


@pytest.fixture(scope="module")
def sm_home(tmp_path_factory) -> Path:
    return tmp_path_factory.mktemp("sm_home")


@pytest.fixture(scope="module")
def warmed_backends(sm_home):
    """Start every lifecycle configuration in parallel so each test reuses a hot process."""
    warmed: dict[str, tuple[subprocess.Popen, int, dict]] = {}
    procs: list[subprocess.Popen] = []
    with ThreadPoolExecutor(max_workers=len(_WARM_SCENARIOS)) as pool:
        futures = [pool.submit(_warm_one, sm_home, scenario) for scenario in _WARM_SCENARIOS]
        for future in as_completed(futures):
            name, proc, port, ping = future.result()
            warmed[name] = (proc, port, ping)
            procs.append(proc)
    yield warmed
    for proc in procs:
        _stop(proc)


@pytest.fixture
def warm(warmed_backends):
    return warmed_backends.__getitem__


@pytest.fixture
def backend(sm_home):
    procs = []

    def start(port, **kwargs):
        proc = _spawn(port, SM_HOME=str(sm_home), **kwargs)
        procs.append(proc)
        return proc

    yield start
    for proc in procs:
        _stop(proc)


def test_ping_startup_within_budget(sm_home):
    port = _free_port()
    started = time.monotonic()
    proc = _spawn(port, SM_HOME=str(sm_home))
    try:
        _wait_for_ping(proc, port)
        elapsed = time.monotonic() - started
        assert elapsed < PING_STARTUP_BUDGET, f"/ping took {elapsed:.1f}s (budget {PING_STARTUP_BUDGET}s)"
    finally:
        _stop(proc)


def test_ping_reports_the_instance_token_it_was_launched_with(warm):
    proc, _port, ping = warm("test_ping_reports_the_instance_token_it_was_launched_with")
    assert ping == {"status": "ok", "source": "sm-backend", "instance": "test-token"}
    assert proc.poll() is None


def test_exits_cleanly_when_the_app_closes_its_stdin(warm):
    proc, _port, _ping = warm("test_exits_cleanly_when_the_app_closes_its_stdin")
    proc.stdin.close()
    assert proc.wait(timeout=EXIT_TIMEOUT) == 0
    assert b"mutex" not in proc.stderr.read()


def test_exits_when_the_app_dies_with_unflushed_stdout(warm):
    proc, _port, _ping = warm("test_exits_when_the_app_dies_with_unflushed_stdout")
    proc.stdout.close()
    proc.stderr.close()
    proc.stdin.close()
    assert proc.wait(timeout=EXIT_TIMEOUT) == 0


def test_stdin_eof_is_ignored_without_the_opt_in_flag(warm):
    proc, port, _ping = warm("test_stdin_eof_is_ignored_without_the_opt_in_flag")
    proc.stdin.close()
    time.sleep(2)
    assert proc.poll() is None
    assert _wait_for_ping(proc, port)["status"] == "ok"


@pytest.mark.skipif(sys.platform == "win32", reason="send_signal(SIGTERM) is TerminateProcess on Windows, so there is no graceful exit to assert")
def test_sigterm_exits_cleanly(warm):
    proc, _port, _ping = warm("test_sigterm_exits_cleanly")
    proc.send_signal(signal.SIGTERM)
    assert proc.wait(timeout=EXIT_TIMEOUT) == 0


def _credentials_status(port: int) -> dict:
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/credentials/status", timeout=5) as res:
        return json.loads(res.read())


def test_credentials_come_from_the_app_on_stdin(backend):
    port = _free_port()
    proc = backend(port, SM_CREDENTIALS_ON_STDIN="1", SM_EXIT_ON_STDIN_EOF="1")
    proc.stdin.write(b'{"canvas-token": "t"}\n')
    proc.stdin.flush()
    _wait_for_ping(proc, port)
    assert _credentials_status(port) == {"canvas": True, "llm": False}

    proc.stdin.write(b'{"openai-key": "sk-test"}\n')
    proc.stdin.flush()
    deadline = time.monotonic() + EXIT_TIMEOUT
    while _credentials_status(port)["llm"] is False and time.monotonic() < deadline:
        time.sleep(0.1)
    assert _credentials_status(port) == {"canvas": True, "llm": True}

    proc.stdin.close()
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
