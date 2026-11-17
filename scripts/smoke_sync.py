"""Exercise real frozen sync/indexing against a local Canvas fixture, without accounts."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request


class CanvasFixture(BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path.split("?")[0].removeprefix("/api/v1")
        base = f"http://127.0.0.1:{self.server.server_port}"
        routes = {
            "/courses/1/modules": [{"items": [{"type": "File", "content_id": 11}]}],
            "/courses/1/pages": [],
            "/courses/1/front_page": {"url": "overview", "title": "Overview", "body": "<p>Course notes about software testing and retrieval.</p>", "updated_at": "2026-01-01"},
            "/courses/1": {"syllabus_body": ""},
            "/courses/1/assignments": [],
            "/files/11": {"id": 11, "display_name": "lecture.txt", "updated_at": "2026-01-01", "url": base + "/download"},
        }
        body = b"Software testing uses assertions to compare expected and actual behavior. " * 4 if path == "/download" else json.dumps(routes.get(path)).encode()
        self.send_response(200 if path in routes or path == "/download" else 404)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("executable", type=Path)
    parser.add_argument("--parallel", type=int, default=1)
    args = parser.parse_args()
    fixture = ThreadingHTTPServer(("127.0.0.1", 0), CanvasFixture)
    threading.Thread(target=fixture.serve_forever, daemon=True).start()
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with tempfile.TemporaryDirectory(prefix="Second Mind sync 日本語 ") as home, tempfile.TemporaryFile() as log:
        Path(home, "config.json").write_text(json.dumps({"selected_courses": [1], "memory_enabled": False, "canvas_base_url": f"http://127.0.0.1:{fixture.server_port}"}), encoding="utf-8")
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        env = {**os.environ, "SM_HOME": home, "SM_PORT": str(port), "SM_CREDENTIALS_ON_STDIN": "1", "SM_EXIT_ON_STDIN_EOF": "1", "PYTHONUTF8": "1"}
        proc = subprocess.Popen([str(args.executable.resolve())], env=env, stdin=subprocess.PIPE, stdout=log, stderr=log)
        try:
            proc.stdin.write(b'{"canvas-token":"fixture-token"}\n')
            proc.stdin.flush()
            for attempt in range(180):
                try:
                    with opener.open(f"http://127.0.0.1:{port}/ping", timeout=1):
                        break
                except OSError:
                    if proc.poll() is not None or attempt == 179:
                        raise RuntimeError("backend did not start")
                    time.sleep(0.2)

            def sync():
                request = urllib.request.Request(f"http://127.0.0.1:{port}/courses/1/sync", method="POST")
                with opener.open(request, timeout=180) as response:
                    return [json.loads(line) for line in response if line.strip()]

            with ThreadPoolExecutor(max_workers=args.parallel) as pool:
                results = list(pool.map(lambda _: sync(), range(args.parallel)))
            for events in results:
                print(json.dumps(events), flush=True)
                assert events[-1].get("done") and not events[-1].get("error") and not events[-1].get("failed"), events
            repeated = sync()
            assert repeated[-1] == {"done": True, "new": 0, "changed": 0, "removed": 0, "failed": 0}, repeated
            print("Frozen sync, indexing, and unchanged re-sync: OK", flush=True)
        finally:
            proc.stdin.close()
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
            log.seek(0)
            print(log.read().decode("utf-8", errors="replace"), flush=True)
            fixture.shutdown()
            fixture.server_close()


if __name__ == "__main__":
    main()
