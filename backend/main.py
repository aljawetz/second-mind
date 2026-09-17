"""Sidecar backend — see docs/architecture/implementation-plan.md."""

import json
import re
import socketserver
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import httpx
import openai
from llama_index.vector_stores.lancedb.base import TableNotFoundError

import canvas
import explain
import generation
import indexing

HOST = "127.0.0.1"
PORT = 8756

# data-model.md §1: no per-student subdirectory — SSB is a local sidecar,
# one student per machine, one OS user account per student, so ~/.ssb/
# itself is already the physical isolation boundary design spec §5.1 is
# about. A <student_id> layer inside it would isolate against nothing real
# for this architecture (revisited and deliberately simplified — not an
# oversight).
SSB_HOME = Path.home() / ".ssb"

ASK_PATH = re.compile(r"^/courses/(\d+)/ask$")
ASSIGNMENTS_PATH = re.compile(r"^/courses/(\d+)/assignments$")
EXPLAIN_PATH = re.compile(r"^/courses/(\d+)/assignments/(\d+)/explain$")


class ThreadingHTTPServer(socketserver.ThreadingMixIn, HTTPServer):
    """Handle each request in its own thread. Needed once /ask streams a
    response over several seconds — without this, a single-threaded server
    blocks every other request (even /ping) for the whole stream duration."""

    daemon_threads = True


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
    # BaseHTTPRequestHandler defaults to declaring HTTP/1.0, under which
    # Transfer-Encoding: chunked (/ask's streaming response) is technically
    # undefined — real clients tolerated it (verified: curl, Node's
    # undici), but declaring 1.1 is the actual correct fix rather than
    # relying on that leniency. Every response here already sends either
    # Content-Length or proper chunked framing, so 1.1 keep-alive is safe.
    protocol_version = "HTTP/1.1"

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
            assignments_match = ASSIGNMENTS_PATH.match(self.path)
            if assignments_match:
                self._handle_list_assignments(assignments_match.group(1))
                return
            self.send_response(404)
            self.end_headers()

    def _canvas_error(self, e: Exception) -> tuple[int, dict]:
        # Error shape/codes per overview.md's documented contract.
        if isinstance(e, canvas.CanvasError):
            return 401, {"error": {"code": "canvas_auth_failed", "message": "no Canvas token stored"}}
        if isinstance(e, httpx.HTTPStatusError):
            if e.response.status_code == 401:
                return 401, {"error": {"code": "canvas_auth_failed", "message": "Canvas token invalid or expired"}}
            return 502, {"error": {"code": "canvas_error", "message": str(e)}}
        return 503, {"error": {"code": "canvas_unreachable", "message": "could not reach Canvas"}}  # httpx.TransportError

    def _handle_list_courses(self):
        try:
            raw = canvas.list_courses()
        except (canvas.CanvasError, httpx.HTTPStatusError, httpx.TransportError) as e:
            self._send_json(*self._canvas_error(e))
            return

        courses = [
            {"id": c["id"], "code": c.get("course_code"), "name": c.get("name")}
            for c in raw
            if c.get("name")  # some real courses come back with no name/code — skip, not usefully selectable
        ]
        self._send_json(200, {"courses": courses})

    def _handle_list_assignments(self, course_id: str):
        try:
            raw = canvas.list_assignments(int(course_id))
        except (canvas.CanvasError, httpx.HTTPStatusError, httpx.TransportError) as e:
            self._send_json(*self._canvas_error(e))
            return

        assignments = [
            {
                "id": a["id"],
                "name": a.get("name", ""),
                "due_at": a.get("due_at"),
                "points_possible": a.get("points_possible"),
                "description": explain.html_to_text(a.get("description") or ""),
            }
            for a in raw
        ]
        self._send_json(200, {"assignments": assignments})

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
            return

        ask_match = ASK_PATH.match(self.path)
        if ask_match:
            self._handle_ask(ask_match.group(1))
            return

        explain_match = EXPLAIN_PATH.match(self.path)
        if explain_match:
            self._handle_explain(explain_match.group(1), explain_match.group(2))
            return

        self.send_response(404)
        self.end_headers()

    def _write_chunk(self, payload: dict):
        # Manual chunked transfer encoding — verified against a real client
        # (implementation-plan.md Step 9) to deliver each line as soon as
        # it's written, not buffered until the response closes.
        line = (json.dumps(payload) + "\n").encode()
        self.wfile.write(f"{len(line):x}\r\n".encode())
        self.wfile.write(line)
        self.wfile.write(b"\r\n")
        self.wfile.flush()

    def _handle_ask(self, course_id: str):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            self._send_json(400, {"error": {"code": "bad_request", "message": "invalid JSON"}})
            return
        question = data.get("question", "").strip()
        mode = data.get("mode", "answer")
        if not question:
            self._send_json(400, {"error": {"code": "bad_request", "message": "question is required"}})
            return

        # Errors here happen before any bytes are written — response.status
        # can still be set cleanly. Retrieval (TableNotFoundError) and the
        # LLM call (openai.*Error) both happen synchronously inside
        # engine.query(), confirmed against a real index and a real,
        # deliberately-invalid key (Step 9) — nothing here is deferred to
        # response_gen, so no error can surface after streaming starts.
        not_indexed = False
        try:
            db_path = SSB_HOME / "index.lancedb"
            index = indexing.load_index(db_path, f"course_{course_id}")
            engine = generation.build_query_engine(index, socratic=(mode == "socratic"), streaming=True)
            response = engine.query(question)
        except TableNotFoundError:
            # Course not indexed yet — indistinguishable from "nothing
            # relevant retrieved" at the response shape level (§7). Streamed
            # the same way as every other 200, not a one-off plain-JSON
            # shape, so the frontend has exactly one success format to parse.
            not_indexed = True
        except RuntimeError as e:
            self._send_json(401, {"error": {"code": "llm_auth_failed", "message": str(e)}})
            return
        except openai.AuthenticationError:
            self._send_json(401, {"error": {"code": "llm_auth_failed", "message": "OpenAI API key invalid or expired"}})
            return
        except openai.RateLimitError as e:
            if e.code == "insufficient_quota":
                self._send_json(402, {"error": {"code": "llm_quota_exceeded", "message": "OpenAI quota exceeded"}})
            else:
                self._send_json(429, {"error": {"code": "llm_rate_limited", "message": "OpenAI rate limit hit — try again shortly"}})
            return

        citations = [] if not_indexed else generation.build_citations(response.source_nodes)
        grounded = bool(citations)

        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.send_header("Transfer-Encoding", "chunked")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self._write_chunk({"citations": citations, "grounded": grounded})
        if grounded:
            # Real tokens only when grounded — an ungrounded query never
            # reaches the LLM at all (CitationQueryEngine short-circuits
            # when every node fails the similarity cutoff), so response_gen
            # would otherwise yield the framework's raw "Empty Response".
            for token in response.response_gen:
                self._write_chunk({"delta": token})
        else:
            self._write_chunk({"delta": generation.NOT_COVERED_MESSAGE})
        self._write_chunk({"done": True})
        self.wfile.write(b"0\r\n\r\n")
        self.wfile.flush()

    def _handle_explain(self, course_id: str, assignment_id: str):
        # Drain any request body (overview.md documents Request: {}) — not
        # otherwise used.
        length = int(self.headers.get("Content-Length", 0))
        if length:
            self.rfile.read(length)

        try:
            assignment = canvas.get_assignment(int(course_id), int(assignment_id))
        except (canvas.CanvasError, httpx.HTTPStatusError, httpx.TransportError) as e:
            self._send_json(*self._canvas_error(e))
            return

        if assignment is None:
            # get_assignment() degrades both 403 and 404 to None
            # (canvas.py's documented policy) — overview.md's not_found
            # covers "bad or stale ID," which is the reachable case here.
            self._send_json(404, {"error": {"code": "not_found", "message": "assignment not found"}})
            return

        name = assignment.get("name", "")
        description_text = explain.html_to_text(assignment.get("description") or "")

        try:
            breakdown = explain.build_breakdown(name, description_text)
        except RuntimeError as e:
            self._send_json(401, {"error": {"code": "llm_auth_failed", "message": str(e)}})
            return
        except openai.AuthenticationError:
            self._send_json(401, {"error": {"code": "llm_auth_failed", "message": "OpenAI API key invalid or expired"}})
            return
        except openai.RateLimitError as e:
            if e.code == "insufficient_quota":
                self._send_json(402, {"error": {"code": "llm_quota_exceeded", "message": "OpenAI quota exceeded"}})
            else:
                self._send_json(429, {"error": {"code": "llm_rate_limited", "message": "OpenAI rate limit hit — try again shortly"}})
            return

        try:
            db_path = SSB_HOME / "index.lancedb"
            index = indexing.load_index(db_path, f"course_{course_id}")
            pointers = explain.build_pointers(index, name, description_text)
        except TableNotFoundError:
            # Course not indexed yet — same graceful degrade as /ask.
            pointers = []

        self._send_json(200, {"breakdown": breakdown, "pointers": pointers})

    def log_message(self, format, *args):
        pass  # keep stdout quiet; this is a sidecar, not a dev console


if __name__ == "__main__":
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    server.serve_forever()
