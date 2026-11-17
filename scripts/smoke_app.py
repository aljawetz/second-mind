"""Launch an installed Windows app and verify its backend starts and stops.

Uses an isolated data directory and refuses to interrupt an already-running app.
"""

import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import time
import urllib.request


def listening() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", 8756), timeout=1):
            return True
    except (ConnectionRefusedError, TimeoutError):
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("executable", type=Path)
    args = parser.parse_args()
    if os.name != "nt":
        parser.error("this smoke check targets the Windows app")
    if listening():
        parser.error("port 8756 is in use; close Second Mind before running this check")
    startup = subprocess.STARTUPINFO()
    startup.dwFlags = subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = subprocess.SW_HIDE
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with tempfile.TemporaryDirectory(prefix="Second Mind installed 日本語 ") as directory:
        env = {**os.environ, "SM_HOME": directory, "PYTHONUTF8": "1"}
        # Do not inherit test overrides: the frontend talks to port 8756.
        env.pop("SM_PORT", None)
        proc = subprocess.Popen([str(args.executable.resolve())], env=env, startupinfo=startup)
        try:
            deadline = time.monotonic() + 180
            while True:
                if proc.poll() is not None:
                    raise RuntimeError(f"installed app exited early ({proc.returncode})")
                try:
                    with opener.open("http://127.0.0.1:8756/ping", timeout=2) as response:
                        ping = json.load(response)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError("installed app did not start its backend")
                    time.sleep(0.5)
            assert ping["source"] == "sm-backend" and ping.get("instance"), ping
            with opener.open("http://127.0.0.1:8756/config", timeout=5) as response:
                assert json.load(response) == {}, "backend did not use the isolated data directory"
        finally:
            if proc.poll() is None:
                proc.terminate()
            proc.wait(timeout=15)
            deadline = time.monotonic() + 15
            while listening():
                if time.monotonic() >= deadline:
                    raise RuntimeError("backend outlived the installed app")
                time.sleep(0.2)
    print("Installed app startup, backend resources, and child-process cleanup: OK", flush=True)


if __name__ == "__main__":
    main()
