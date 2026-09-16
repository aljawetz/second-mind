"""Sidecar proof of concept — Step 1 of the implementation plan.

Deliberately stdlib-only, zero dependencies. This step proves the Tauri sidecar
mechanism itself (process spawn, binary naming, dev/frozen path resolution),
not any real backend logic — that comes with FastAPI/LlamaIndex in later steps.
"""

import json
from http.server import BaseHTTPRequestHandler, HTTPServer

HOST = "127.0.0.1"
PORT = 8756


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/ping":
            body = json.dumps({"status": "ok", "source": "ssb-backend"}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            # Bound to 127.0.0.1 only, reachable solely by this app's own
            # webview — its origin differs from http://127.0.0.1:8756, so
            # WebKit blocks the fetch response without this header.
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass  # keep stdout quiet; this is a sidecar, not a dev console


if __name__ == "__main__":
    server = HTTPServer((HOST, PORT), Handler)
    server.serve_forever()
