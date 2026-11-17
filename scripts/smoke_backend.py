"""Check a source or frozen backend using an isolated home and a free port.

python scripts/smoke_backend.py app/src-tauri/binaries/sm-backend/sm-backend.exe
python scripts/smoke_backend.py --source
"""

import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("executable", nargs="?", type=Path)
    parser.add_argument("--source", action="store_true")
    parser.add_argument("--timeout", type=int, default=120)
    args = parser.parse_args()
    if args.source:
        command = [sys.executable, str(ROOT / "backend" / "main.py")]
    elif args.executable:
        command = [str(args.executable.resolve())]
        if os.name == "nt":
            runtime = args.executable.resolve().parent / "_internal"
            for required in ("tesseract/tesseract.exe", "tesseract/tessdata/eng.traineddata", "tesseract/doc/LICENSE"):
                if not (runtime / required).is_file():
                    raise FileNotFoundError(f"Missing bundled OCR resource: {runtime / required}")
    else:
        parser.error("pass a backend executable or --source")

    subprocess.run([*command, "--self-test"], check=True, timeout=300)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    # Spaces and non-ASCII names occur in real Windows user profiles.
    with tempfile.TemporaryDirectory(prefix="Second Mind 日本語 ") as directory, tempfile.TemporaryFile() as log:
        env = {**os.environ, "SM_HOME": directory, "SM_PORT": str(port),
               "SM_INSTANCE_TOKEN": "smoke-test", "SM_CREDENTIALS_ON_STDIN": "1",
               "SM_EXIT_ON_STDIN_EOF": "1", "PYTHONUTF8": "1"}
        proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=log, stderr=log, env=env)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

        def get(path):
            with opener.open(f"http://127.0.0.1:{port}{path}", timeout=2) as response:
                return json.load(response)

        try:
            proc.stdin.write(b"{}\n")
            proc.stdin.flush()
            deadline = time.monotonic() + args.timeout
            while True:
                if proc.poll() is not None:
                    raise RuntimeError(f"backend exited before /ping ({proc.returncode})")
                try:
                    ping = get("/ping")
                    break
                except OSError as error:
                    if isinstance(getattr(error, "reason", error), PermissionError):
                        raise RuntimeError("Localhost access is blocked; run outside the restricted sandbox") from error
                    if time.monotonic() >= deadline:
                        raise TimeoutError("backend did not answer /ping") from error
                    time.sleep(0.2)
            assert ping == {"status": "ok", "source": "sm-backend", "instance": "smoke-test"}, ping
            assert get("/config") == {}, "isolated config was not empty"
            assert get("/credentials/status") == {"canvas": False, "llm": False}
            proc.stdin.close()
            assert proc.wait(timeout=15) == 0, "backend failed to exit when the app closed"
            print("Backend HTTP, credentials handoff, isolated home, and shutdown: OK", flush=True)
        except BaseException:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
            log.seek(0)
            print(log.read().decode("utf-8", errors="replace"), file=sys.stderr)
            raise


if __name__ == "__main__":
    main()
