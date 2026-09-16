"""Sidecar backend — see docs/architecture/implementation-plan.md."""

import json
from http.server import BaseHTTPRequestHandler, HTTPServer

import httpx

import canvas

HOST = "127.0.0.1"
PORT = 8756


def validate_credential(kind: str, value: str) -> tuple[bool, str]:
    """Format check only (Step 2) — not a real Canvas/OpenAI call yet (Step 3
    upgrades this exact endpoint to do that, same interface)."""
    value = value.strip()
    if not value:
        return False, "empty"
    if kind == "canvas":
        if len(value) < 20:
            return False, "too short for a Canvas API token"
        return True, ""
    if kind == "openai":
        if not value.startswith("sk-"):
            return False, "OpenAI keys start with 'sk-'"
        if len(value) < 20:
            return False, "too short for an OpenAI API key"
        return True, ""
    return False, f"unknown credential kind '{kind}'"


class Handler(BaseHTTPRequestHandler):
    def _send_json(self, status: int, payload: dict):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        # Bound to 127.0.0.1 only, reachable solely by this app's own
        # webview — its origin differs from http://127.0.0.1:8756, so
        # WebKit blocks the fetch response without this header.
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/ping":
            self._send_json(200, {"status": "ok", "source": "ssb-backend"})
        elif self.path == "/courses":
            self._handle_list_courses()
        else:
            self.send_response(404)
            self.end_headers()

    def _handle_list_courses(self):
        # Error shape/codes per overview.md's documented contract.
        try:
            raw = canvas.list_courses()
        except canvas.CanvasError:
            self._send_json(401, {"error": {"code": "canvas_auth_failed", "message": "no Canvas token stored"}})
            return
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                self._send_json(401, {"error": {"code": "canvas_auth_failed", "message": "Canvas token invalid or expired"}})
            else:
                self._send_json(502, {"error": {"code": "canvas_error", "message": str(e)}})
            return
        except httpx.TransportError:
            self._send_json(503, {"error": {"code": "canvas_unreachable", "message": "could not reach Canvas"}})
            return

        courses = [
            {"id": c["id"], "code": c.get("course_code"), "name": c.get("name")}
            for c in raw
            if c.get("name")  # some real courses come back with no name/code — skip, not usefully selectable
        ]
        self._send_json(200, {"courses": courses})

    def do_POST(self):
        if self.path == "/credentials/validate":
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length)
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                self._send_json(400, {"error": {"code": "bad_request", "message": "invalid JSON"}})
                return
            valid, reason = validate_credential(data.get("kind", ""), data.get("value", ""))
            self._send_json(200, {"valid": valid, "reason": reason})
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass  # keep stdout quiet; this is a sidecar, not a dev console


if __name__ == "__main__":
    server = HTTPServer((HOST, PORT), Handler)
    server.serve_forever()
