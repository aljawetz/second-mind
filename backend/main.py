"""Sidecar backend — see docs/architecture/implementation-plan.md."""

import errno
import json
import multiprocessing
import os
import re
import signal
import socketserver
import sys
import threading
import traceback
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import httpx
import openai
from llama_index.vector_stores.lancedb.base import TableNotFoundError
from onnxruntime.capi.onnxruntime_pybind11_state import NoSuchFile as OnnxModelFileMissing

import canvas
import chat
import config
import course_sync
import courses
import explain
import generation
import indexing
import llm
import sessions

HOST = "127.0.0.1"
# SM_PORT exists for tests/test_main_lifecycle.py only — the app always
# uses 8756 (app/src/sidecar.ts and the http capability scope hardcode it).
PORT = int(os.environ.get("SM_PORT", "8756"))

# Random per-launch value the Tauri app passes in and checks against
# /ping, so the frontend can tell its own backend apart from a stale one
# left over from an earlier launch still holding the port.
INSTANCE_TOKEN = os.environ.get("SM_INSTANCE_TOKEN", "")

# data-model.md §1: no per-student subdirectory — Second Mind is a local sidecar,
# one student per machine, one OS user account per student, so ~/.secondmind/
# itself is already the physical isolation boundary design spec §5.1 is
# about. A <student_id> layer inside it would isolate against nothing real
# for this architecture (revisited and deliberately simplified — not an
# oversight).
SM_HOME = Path.home() / ".secondmind"
canvas.SM_HOME = SM_HOME

# Similarity cutoff for chat's course search, kept separate from the
# assignment explainer's so the two can be tuned apart. Tried 0.4 against
# 0.5 on 67 questions across three courses: same number of good answers,
# one more made-up course fact, so 0.5 stays — see
# docs/evaluations/2026-09-23-ask-modes/report.md.
CHAT_SIMILARITY_CUTOFF = generation.SIMILARITY_CUTOFF

COURSE_PATH = re.compile(r"^/courses/(\d+)$")
UNSELECT_PATH = re.compile(r"^/courses/(\d+)/unselect$")
ASK_PATH = re.compile(r"^/courses/(\d+)/ask$")
SYNC_PATH = re.compile(r"^/courses/(\d+)/sync$")
ASSIGNMENTS_PATH = re.compile(r"^/courses/(\d+)/assignments$")
EXPLAIN_PATH = re.compile(r"^/courses/(\d+)/assignments/(\d+)/explain$")
SESSION_LIST_PATH = re.compile(r"^/courses/(\d+)/sessions$")
SESSION_START_PATH = re.compile(r"^/courses/(\d+)/sessions/start$")
SESSION_DETAIL_PATH = re.compile(r"^/courses/(\d+)/sessions/([\w-]+)$")
SESSION_RENAME_PATH = re.compile(r"^/courses/(\d+)/sessions/([\w-]+)/rename$")
SESSION_STOP_PATH = re.compile(r"^/sessions/([\w-]+)/stop$")
SESSION_NOTES_PATH = re.compile(r"^/sessions/([\w-]+)/notes$")


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
            self._send_json(200, {"status": "ok", "source": "sm-backend", "instance": INSTANCE_TOKEN})
        elif self.path == "/courses":
            self._handle_list_courses()
        elif self.path == "/credentials/status":
            self._send_json(200, config.credentials_status())
        elif self.path == "/config":
            self._send_json(200, config.read_config(SM_HOME))
        else:
            assignments_match = ASSIGNMENTS_PATH.match(self.path)
            if assignments_match:
                self._handle_list_assignments(assignments_match.group(1))
                return
            list_match = SESSION_LIST_PATH.match(self.path)
            if list_match:
                self._handle_list_sessions(list_match.group(1))
                return
            detail_match = SESSION_DETAIL_PATH.match(self.path)
            if detail_match:
                self._handle_session_detail(detail_match.group(1), detail_match.group(2))
                return
            self._send_json(404, {"error": {"code": "not_found", "message": "no such route"}})

    def _canvas_error(self, e: Exception) -> tuple[int, dict]:
        # Error shape/codes per overview.md's documented contract.
        if isinstance(e, canvas.CanvasError):
            return 401, {"error": {"code": "canvas_auth_failed", "message": "no Canvas token stored"}}
        if isinstance(e, httpx.HTTPStatusError):
            if e.response.status_code == 401:
                return 401, {"error": {"code": "canvas_auth_failed", "message": "Canvas token invalid or expired"}}
            return 502, {"error": {"code": "canvas_error", "message": str(e)}}
        return 503, {"error": {"code": "canvas_unreachable", "message": "could not reach Canvas"}}  # httpx.TransportError

    def _llm_error(self, e: Exception) -> tuple[int, dict]:
        if isinstance(e, RuntimeError):
            return 401, {"error": {"code": "llm_auth_failed", "message": str(e)}}
        if isinstance(e, openai.AuthenticationError):
            return 401, {"error": {"code": "llm_auth_failed", "message": "OpenAI API key invalid or expired"}}
        if isinstance(e, openai.RateLimitError):
            if e.code == "insufficient_quota":
                return 402, {"error": {"code": "llm_quota_exceeded", "message": "OpenAI quota exceeded"}}
            return 429, {"error": {"code": "llm_rate_limited", "message": "OpenAI rate limit hit — try again shortly"}}
        return 503, {"error": {"code": "llm_unreachable", "message": "could not reach the LLM provider"}}  # openai.APIConnectionError

    def _course_selected(self, course_id: int) -> bool:
        # Real not_found gap (implementation-plan.md Step 13): Canvas
        # returns the same 404 whether a course doesn't exist or just isn't
        # accessible to this token, so canvas.py's own degrade-to-empty
        # policy can't distinguish "bad id" from "no permission" — but this
        # app's own selected_courses list is a real, local, unambiguous
        # source of truth for "is this a course we know about at all."
        return course_id in config.read_config(SM_HOME).get("selected_courses", [])

    def _not_found(self, message: str = "no such course"):
        self._send_json(404, {"error": {"code": "not_found", "message": message}})

    def _handle_list_courses(self):
        try:
            raw = canvas.list_courses()
        except (canvas.CanvasError, httpx.HTTPStatusError, httpx.TransportError) as e:
            self._send_json(*self._canvas_error(e))
            return

        course_list = [
            {"id": c["id"], "code": c.get("course_code"), "name": c.get("name")}
            for c in raw
            if c.get("name")  # some real courses come back with no name/code — skip, not usefully selectable
        ]
        self._send_json(200, {"courses": course_list})

    def _handle_list_assignments(self, course_id: str):
        if not self._course_selected(int(course_id)):
            self._not_found()
            return
        try:
            raw = canvas.list_assignments(int(course_id))
        except (canvas.CanvasError, httpx.HTTPStatusError, httpx.TransportError) as e:
            self._send_json(*self._canvas_error(e))
            return

        assignments = []
        for a in raw:
            submission = a.get("submission") or {}
            assignments.append(
                {
                    "id": a["id"],
                    "name": a.get("name", ""),
                    "due_at": a.get("due_at"),
                    "points_possible": a.get("points_possible"),
                    "description": explain.html_to_text(a.get("description") or ""),
                    # Real Canvas submission status (canvas.list_assignments's
                    # include[]=submission), not guessed from due date — a
                    # workflow_state of "unsubmitted" (or no submission object
                    # at all, e.g. a not-for-credit assignment) means not done.
                    "submitted": submission.get("workflow_state") not in (None, "unsubmitted"),
                    "late": bool(submission.get("late")),
                    "missing": bool(submission.get("missing")),
                }
            )
        self._send_json(200, {"assignments": assignments})

    def _handle_list_sessions(self, course_id: str):
        if not self._course_selected(int(course_id)):
            self._not_found()
            return
        self._send_json(200, {"sessions": sessions.list_sessions(SM_HOME, int(course_id))})

    def _handle_session_detail(self, course_id: str, session_id: str):
        if not self._course_selected(int(course_id)):
            self._not_found()
            return
        detail = sessions.get_session_detail(SM_HOME, int(course_id), session_id)
        if detail is None:
            self._send_json(404, {"error": {"code": "not_found", "message": "no such session"}})
            return
        self._send_json(200, detail)

    def do_POST(self):
        if self.path == "/config":
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length)
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                self._send_json(400, {"error": {"code": "bad_request", "message": "invalid JSON"}})
                return
            merged = {**config.read_config(SM_HOME), **data}
            if merged.get("canvas_base_url"):
                merged["canvas_base_url"] = config.normalize_canvas_base_url(merged["canvas_base_url"])
            config.write_config(SM_HOME, merged)
            self._send_json(200, merged)
            return

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

        unselect_match = UNSELECT_PATH.match(self.path)
        if unselect_match:
            self._handle_unselect(unselect_match.group(1))
            return

        ask_match = ASK_PATH.match(self.path)
        if ask_match:
            self._handle_ask(ask_match.group(1))
            return

        sync_match = SYNC_PATH.match(self.path)
        if sync_match:
            self._handle_course_sync(sync_match.group(1))
            return

        explain_match = EXPLAIN_PATH.match(self.path)
        if explain_match:
            self._handle_explain(explain_match.group(1), explain_match.group(2))
            return

        session_start_match = SESSION_START_PATH.match(self.path)
        if session_start_match:
            self._handle_session_start(session_start_match.group(1))
            return

        session_stop_match = SESSION_STOP_PATH.match(self.path)
        if session_stop_match:
            self._handle_session_stop(session_stop_match.group(1))
            return

        session_notes_match = SESSION_NOTES_PATH.match(self.path)
        if session_notes_match:
            self._handle_session_notes(session_notes_match.group(1))
            return

        rename_match = SESSION_RENAME_PATH.match(self.path)
        if rename_match:
            self._handle_session_rename(rename_match.group(1), rename_match.group(2))
            return

        self._send_json(404, {"error": {"code": "not_found", "message": "no such route"}})

    def do_DELETE(self):
        detail_match = SESSION_DETAIL_PATH.match(self.path)
        if detail_match:
            self._handle_session_delete(detail_match.group(1), detail_match.group(2))
            return
        course_match = COURSE_PATH.match(self.path)
        if course_match:
            self._handle_delete_course(course_match.group(1))
            return
        self._send_json(404, {"error": {"code": "not_found", "message": "no such route"}})

    def _handle_unselect(self, course_id: str):
        if not self._course_selected(int(course_id)):
            self._not_found()
            return
        courses.unselect_course(SM_HOME, int(course_id))
        self._send_json(200, {"status": "unselected"})

    def _handle_delete_course(self, course_id: str):
        db_path = SM_HOME / "index.lancedb"
        if not courses.has_local_data(SM_HOME, int(course_id), db_path):
            self._not_found()
            return
        courses.delete_course(SM_HOME, int(course_id), db_path)
        self._send_json(200, {"status": "deleted"})

    def _handle_session_start(self, course_id: str):
        if not self._course_selected(int(course_id)):
            self._not_found()
            return
        self._send_json(200, sessions.start_session(SM_HOME, int(course_id)))

    def _handle_session_stop(self, session_id: str):
        length = int(self.headers.get("Content-Length", 0))
        audio_bytes = self.rfile.read(length)
        try:
            result = sessions.stop_session(session_id, audio_bytes, SM_HOME / "index.lancedb")
        except KeyError:
            self._send_json(404, {"error": {"code": "not_found", "message": "no such session"}})
            return
        self._send_json(200, result)

    def _handle_session_notes(self, session_id: str):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            self._send_json(400, {"error": {"code": "bad_request", "message": "invalid JSON"}})
            return
        try:
            sessions.save_notes(session_id, data.get("text", ""))
        except KeyError:
            self._send_json(404, {"error": {"code": "not_found", "message": "no such session"}})
            return
        self._send_json(200, {"status": "saved"})

    def _handle_session_rename(self, course_id: str, session_id: str):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            self._send_json(400, {"error": {"code": "bad_request", "message": "invalid JSON"}})
            return
        if not self._course_selected(int(course_id)):
            self._not_found()
            return
        try:
            sessions.rename_session(SM_HOME, int(course_id), session_id, data.get("title", ""))
        except KeyError:
            self._send_json(404, {"error": {"code": "not_found", "message": "no such session"}})
            return
        self._send_json(200, {"status": "renamed"})

    def _handle_session_delete(self, course_id: str, session_id: str):
        if not self._course_selected(int(course_id)):
            self._not_found()
            return
        try:
            sessions.delete_session(SM_HOME, int(course_id), session_id, SM_HOME / "index.lancedb")
        except KeyError:
            self._send_json(404, {"error": {"code": "not_found", "message": "no such session"}})
            return
        self._send_json(200, {"status": "deleted"})

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
        if not self._course_selected(int(course_id)):
            self._not_found()
            return
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            self._send_json(400, {"error": {"code": "bad_request", "message": "invalid JSON"}})
            return
        question = data.get("question", "").strip()
        if not question:
            self._send_json(400, {"error": {"code": "bad_request", "message": "question is required"}})
            return
        try:
            history = chat.parse_history(data.get("history"))
        except ValueError as e:
            self._send_json(400, {"error": {"code": "bad_request", "message": str(e)}})
            return
        # No local copy of course names exists (config.json keeps ids only),
        # so the app sends the one it shows in the sidebar.
        course_name = str(data.get("course_name") or "this course")

        # chat.answer() yields nothing until the model starts writing, so
        # everything that can fail early (missing key, embedding model files,
        # searching, the first model calls) fails here, before any response
        # bytes, and still gets a clean status code.
        try:
            try:
                index = indexing.load_index(SM_HOME / "index.lancedb", f"course_{course_id}")
            except TableNotFoundError:
                # Course not indexed yet: every search comes back empty and the
                # model says it couldn't find anything, same as a real miss.
                index = None
            events = chat.answer(
                question, history, course_name, chat.make_search(index, CHAT_SIMILARITY_CUTOFF), llm.OpenAIProvider()
            )
            first = next(events)
        except OnnxModelFileMissing:
            self._send_json(500, {"error": {"code": "model_files_missing", "message": "the local embedding model is missing or corrupted"}})
            return
        except (RuntimeError, openai.AuthenticationError, openai.RateLimitError, openai.APIConnectionError) as e:
            self._send_json(*self._llm_error(e))
            return

        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.send_header("Transfer-Encoding", "chunked")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        try:
            self._write_chunk(first)
            for event in events:
                self._write_chunk(event)
        except (BrokenPipeError, ConnectionResetError):
            return  # the app closed the request (student navigated away)
        except Exception as e:
            # Something failed after the answer started streaming (a later
            # search round, or the model connection dropping). The status line
            # is long gone, so the error travels as a stream event instead.
            traceback.print_exc()
            llm_errors = (RuntimeError, openai.AuthenticationError, openai.RateLimitError, openai.APIConnectionError)
            message = self._llm_error(e)[1]["error"]["message"] if isinstance(e, llm_errors) else "the answer was interrupted"
            self._write_chunk({"error": message})
            self._write_chunk({"done": True})
        self.wfile.write(b"0\r\n\r\n")
        self.wfile.flush()

    def _handle_course_sync(self, course_id: str):
        if not self._course_selected(int(course_id)):
            self._not_found()
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.send_header("Transfer-Encoding", "chunked")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        for event in course_sync.sync_course(int(course_id), SM_HOME):
            self._write_chunk(event)
        self.wfile.write(b"0\r\n\r\n")
        self.wfile.flush()

    def _handle_explain(self, course_id: str, assignment_id: str):
        if not self._course_selected(int(course_id)):
            self._not_found()
            return
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
        except (RuntimeError, openai.AuthenticationError, openai.RateLimitError, openai.APIConnectionError) as e:
            self._send_json(*self._llm_error(e))
            return

        try:
            db_path = SM_HOME / "index.lancedb"
            index = indexing.load_index(db_path, f"course_{course_id}")
            pointers = explain.build_pointers(index, name, description_text)
        except TableNotFoundError:
            # Course not indexed yet — same graceful degrade as /ask.
            pointers = []
        except OnnxModelFileMissing:
            self._send_json(500, {"error": {"code": "model_files_missing", "message": "the local embedding model is missing or corrupted"}})
            return

        self._send_json(200, {"breakdown": breakdown, "pointers": pointers})

    def log_message(self, format, *args):
        pass  # keep stdout quiet; this is a sidecar, not a dev console


def _exit_now(code: int) -> None:
    """os._exit, not sys.exit: skips interpreter teardown, where ONNX
    Runtime's and Arrow's native destructors can race on macOS and abort
    with "recursive_mutex lock failed" (seen in the Copilot SDK spike).
    Nothing needs flushing beyond stdio — every write this backend makes
    (LanceDB, manifest.db, config.json) completes inside its request.

    Flushing is best-effort: when the app died, it closed the stdout/stderr
    pipes it was reading too, so flushing buffered output (course_sync's
    print()) raises BrokenPipeError — which must not stop the exit."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.flush()
        except (OSError, ValueError, AttributeError):
            pass
    os._exit(code)


def _exit_when_app_closes() -> None:
    """The Tauri app holds the write end of our stdin for as long as it
    runs and never writes to it, so EOF means the app is gone — quit,
    crash, or force quit alike. Without this the backend outlived the app
    and kept port 8756, and the next launch talked to the stale process."""
    try:
        while sys.stdin.buffer.read(4096):
            pass
    finally:
        _exit_now(0)


if __name__ == "__main__":
    # Required before anything that might use multiprocessing (faster-whisper's
    # transcription backend does) — without this, the frozen PyInstaller binary
    # re-executes this entire script every time a worker process is spawned,
    # which recursively re-spawns more workers. Confirmed as a real, genuine
    # fork bomb during Step 12's development, not a theoretical risk.
    multiprocessing.freeze_support()

    # stdout is a pipe to the Tauri app, so Python block-buffers it: sync's
    # "[course_sync] skipping ..." lines sat unseen in the buffer instead of
    # reaching the app's [backend] log. Line buffering delivers each line.
    if sys.stdout is not None:
        sys.stdout.reconfigure(line_buffering=True)

    # SIGTERM (which PyInstaller's bootloader forwards) exits the same way.
    signal.signal(signal.SIGTERM, lambda *_: _exit_now(0))

    if os.environ.get("SM_EXIT_ON_STDIN_EOF") == "1" and sys.stdin is not None:
        threading.Thread(target=_exit_when_app_closes, name="app-watchdog", daemon=True).start()

    try:
        server = ThreadingHTTPServer((HOST, PORT), Handler)
    except OSError as e:
        if e.errno != errno.EADDRINUSE:
            raise
        print(
            f"sm-backend: port {PORT} is already in use, most likely by another "
            "Second Mind backend that is still running; exiting",
            file=sys.stderr,
        )
        _exit_now(1)
    server.serve_forever()
