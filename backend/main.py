"""Sidecar backend — see docs/architecture/implementation-plan.md."""

import errno
import itertools
import json
import multiprocessing
import os
import re
import signal
import socketserver
import sqlite3
import sys
import threading
import traceback
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs

import httpx
import openai

import canvas
import config
import credentials
import providers

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
SM_HOME = Path(os.environ.get("SM_HOME", str(Path.home() / ".secondmind")))
canvas.SM_HOME = SM_HOME
providers.SM_HOME = SM_HOME

# Everything a model call can raise that _llm_error turns into a clean error:
# RuntimeError is a missing key or an unknown provider in config.json;
# openai.APIError covers OpenAI and DeepSeek (both through the openai SDK),
# CopilotError GitHub Copilot.
LLM_ERRORS = (RuntimeError, openai.APIError, providers.CopilotError)

# Same value as generation.SIMILARITY_CUTOFF — kept here so /ping can be
# served without importing generation (and its LlamaIndex stack) at startup.
# Tried 0.4 against 0.5 on 67 questions across three courses: same number of
# good answers, one more made-up course fact, so 0.5 stays — see
# docs/evaluations/2026-09-23-ask-modes/report.md.
CHAT_SIMILARITY_CUTOFF = 0.5

class _MemoryWorkerProxy:
    """Lazy facade so tests can keep using main.MEMORY_WORKER without importing
    the worker (and memory stack) at main.py import time."""

    def __init__(self) -> None:
        self._worker = None

    def _instance(self):
        if self._worker is None:
            from memory.worker import MemoryWorker

            self._worker = MemoryWorker(_run_memory_job)
        return self._worker

    def __getattr__(self, name):
        return getattr(self._instance(), name)


MEMORY_WORKER = _MemoryWorkerProxy()

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
CONVERSATION_LIST_PATH = re.compile(r"^/courses/(\d+)/conversations$")
CONVERSATION_DETAIL_PATH = re.compile(r"^/courses/(\d+)/conversations/([\w-]+)$")
MEMORY_LIST_PATH = re.compile(r"^/courses/(\d+)/memories$")
MEMORY_ALL_PATH = re.compile(r"^/courses/(\d+)/memories/all$")
MEMORY_DETAIL_PATH = re.compile(r"^/courses/(\d+)/memories/([\w-]+)$")
MEMORY_EDIT_PATH = re.compile(r"^/courses/(\d+)/memories/([\w-]+)/edit$")
STUDY_LIST_PATH = re.compile(r"^/courses/(\d+)/study$")
STUDY_SOURCES_PATH = re.compile(r"^/courses/(\d+)/study/sources$")
STUDY_DETAIL_PATH = re.compile(r"^/courses/(\d+)/study/([\w-]+)$")
STUDY_PROGRESS_PATH = re.compile(r"^/courses/(\d+)/study/([\w-]+)/progress$")
STUDY_EXPORT_PATH = re.compile(r"^/courses/(\d+)/study/([\w-]+)/export$")
# Where "Download as CSV" saves (study.export_csv); tests point it elsewhere.
DOWNLOADS_DIR = Path.home() / "Downloads"
# Same shape as the route ids above, for ids that arrive in a request body
# instead (/ask's conversation_id) and end up in a file path.
SAFE_ID = re.compile(r"[\w-]+")


def _memory_enabled() -> bool:
    # Whether memory should be on by default is still open (agent memory
    # design spec §12, for responsible-AI review); on for the prototype.
    return config.read_config(SM_HOME).get("memory_enabled", True) is not False


def _memory_service(course_id: int, provider=None, conversation_id: str | None = None):
    """provider: the model memory writes need; reads and deletes don't.
    conversation_id: the chat being answered, whose own summary recall skips."""
    import conversations
    import memory_jobs
    from memory import MemoryService

    return MemoryService(
        SM_HOME,
        course_id,
        llm=provider,
        embed=memory_jobs.embed,
        conversation_id=conversation_id,
        # A forgotten memory's chats must not write it back from their
        # running summaries (agent memory design spec §5.7).
        on_forget=lambda cids: conversations.clear_summaries(SM_HOME, course_id, cids),
    )


def _run_memory_job(job: tuple[int, str | None]) -> None:
    """(course, chat): read the chat's new turns, then sweep the course.
    (course, None): just the sweep, which needs no model and so no key."""
    import llm
    import memory_jobs

    course_id, cid = job
    if not (SM_HOME / "courses" / str(course_id)).is_dir():
        return
    with _memory_service(course_id, llm.current_provider() if cid else None) as service:
        if cid:
            memory_jobs.observe_conversation(SM_HOME, course_id, cid, service)
        # Fading (agent memory design spec §5.7): a scan of one course's
        # memories, milliseconds, so after every job rather than every 20th.
        service.sweep()


def queue_startup_memory_jobs() -> None:
    """At startup: turns saved but not yet read by memory when the app last
    quit, then a sweep of every selected course."""
    import memory_jobs

    if not _memory_enabled():
        return
    selected = config.read_config(SM_HOME).get("selected_courses", [])
    for job in memory_jobs.pending(SM_HOME, selected):
        MEMORY_WORKER.submit(job)
    for course_id in selected:
        MEMORY_WORKER.submit((course_id, None))


def _parse_include_inactive(query: str) -> bool:
    val = parse_qs(query).get("include_inactive", [""])[0].strip().lower()
    return val in ("1", "true", "yes")


def _memory_json(m) -> dict:
    def iso(t):
        return t.isoformat() if t else None

    return {
        "id": m.id,
        "kind": m.kind,
        "text": m.text,
        "importance": m.importance,
        "event_time": iso(m.event_time),
        "created_at": iso(m.created_at),
        "valid_to": iso(m.valid_to),
        "status": m.status,
    }


class ThreadingHTTPServer(socketserver.ThreadingMixIn, HTTPServer):
    """Handle each request in its own thread. Needed once /ask streams a
    response over several seconds — without this, a single-threaded server
    blocks every other request (even /ping) for the whole stream duration."""

    daemon_threads = True


def validate_credential(kind: str, value: str) -> tuple[bool, str]:
    """Format check only (Step 2) — not a real Canvas/model provider call yet
    (Step 3 upgrades this exact endpoint to do that, same interface). kind is
    "canvas" or a providers.PROVIDERS id."""
    value = value.strip()
    if not value:
        return False, "empty"
    if kind == "canvas":
        if len(value) < 20:
            return False, "too short for a Canvas API token"
        return True, ""
    if kind == providers.COPILOT.id:
        if value.startswith("ghp_"):
            return False, "classic tokens don't work with Copilot — create a fine-grained token with the Copilot Requests permission"
        if not value.startswith(("github_pat_", "gho_", "ghu_")):
            return False, "expected a fine-grained GitHub token (starts with 'github_pat_')"
        if len(value) < 30:
            return False, "too short for a GitHub token"
        return True, ""
    if kind in providers.PROVIDERS:
        # OpenAI and DeepSeek keys share a shape.
        name = providers.PROVIDERS[kind].name
        if not value.startswith("sk-"):
            return False, f"{name} keys start with 'sk-'"
        if len(value) < 20:
            return False, f"too short for a {name} API key"
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
        path, _, query = self.path.partition("?")
        if path == "/ping":
            self._send_json(200, {"status": "ok", "source": "sm-backend", "instance": INSTANCE_TOKEN})
        elif path == "/courses":
            self._handle_list_courses()
        elif path == "/credentials/status":
            try:
                credential = providers.current().credential
            except RuntimeError:
                credential = providers.OPENAI.credential  # unknown provider: its key can't be there either
            self._send_json(200, config.credentials_status(credential))
        elif path == "/config":
            self._send_json(200, config.read_config(SM_HOME))
        else:
            assignments_match = ASSIGNMENTS_PATH.match(path)
            if assignments_match:
                self._handle_list_assignments(assignments_match.group(1))
                return
            list_match = SESSION_LIST_PATH.match(path)
            if list_match:
                self._handle_list_sessions(list_match.group(1))
                return
            detail_match = SESSION_DETAIL_PATH.match(path)
            if detail_match:
                self._handle_session_detail(detail_match.group(1), detail_match.group(2))
                return
            conversation_list_match = CONVERSATION_LIST_PATH.match(path)
            if conversation_list_match:
                self._handle_list_conversations(conversation_list_match.group(1))
                return
            conversation_match = CONVERSATION_DETAIL_PATH.match(path)
            if conversation_match:
                self._handle_conversation_detail(conversation_match.group(1), conversation_match.group(2))
                return
            memory_all_match = MEMORY_ALL_PATH.match(path)
            if memory_all_match:
                self._handle_list_memories(memory_all_match.group(1), True)
                return
            memory_list_match = MEMORY_LIST_PATH.match(path)
            if memory_list_match:
                include_inactive = _parse_include_inactive(query)
                self._handle_list_memories(memory_list_match.group(1), include_inactive)
                return
            study_list_match = STUDY_LIST_PATH.match(path)
            if study_list_match:
                self._handle_list_study(study_list_match.group(1))
                return
            # Before STUDY_DETAIL_PATH, which "sources" would also match.
            study_sources_match = STUDY_SOURCES_PATH.match(path)
            if study_sources_match:
                self._handle_study_sources(study_sources_match.group(1))
                return
            study_detail_match = STUDY_DETAIL_PATH.match(path)
            if study_detail_match:
                self._handle_study_detail(study_detail_match.group(1), study_detail_match.group(2))
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
        if isinstance(e, openai.APIConnectionError) or (isinstance(e, providers.CopilotError) and e.status == 503):
            return 503, {"error": {"code": "llm_unreachable", "message": "could not reach the LLM provider"}}
        try:
            name = providers.current().name
        except RuntimeError:
            name = "The LLM provider"
        if isinstance(e, providers.CopilotError):
            # The runtime's own message is long and mostly headers; the
            # terminal gets it whole, the student gets the short version.
            print(f"[copilot] {e}", file=sys.stderr, flush=True)
            codes = {401: "llm_auth_failed", 402: "llm_quota_exceeded", 429: "llm_rate_limited"}
            missing_permission = "Copilot Requests" in str(e)
            messages = {
                401: "Your GitHub token is missing the Copilot Requests permission — create a new fine-grained token with it"
                if missing_permission
                else f"{name} token invalid, expired, or without a Copilot plan",
                402: f"{name} premium requests used up",
                429: f"{name} rate limit hit — try again shortly",
            }
            if e.status in codes:
                return e.status, {"error": {"code": codes[e.status], "message": messages[e.status]}}
            return 502, {"error": {"code": "llm_error", "message": f"{name} returned an error: {e}"}}
        if isinstance(e, openai.AuthenticationError):
            return 401, {"error": {"code": "llm_auth_failed", "message": f"{name} API key invalid or expired"}}
        # OpenAI reports an empty balance as a 429 with insufficient_quota;
        # DeepSeek as a 402.
        if (isinstance(e, openai.RateLimitError) and e.code == "insufficient_quota") or (
            isinstance(e, openai.APIStatusError) and e.status_code == 402
        ):
            return 402, {"error": {"code": "llm_quota_exceeded", "message": f"{name} quota exceeded"}}
        if isinstance(e, openai.RateLimitError):
            return 429, {"error": {"code": "llm_rate_limited", "message": f"{name} rate limit hit — try again shortly"}}
        return 502, {"error": {"code": "llm_error", "message": f"{name} returned an error: {e}"}}

    def _memory_error(self, e: sqlite3.Error) -> tuple[int, dict]:
        if isinstance(e, sqlite3.OperationalError):
            return 503, {"error": {"code": "memory_busy", "message": "memory store is busy, try again shortly"}}
        return 500, {"error": {"code": "memory_error", "message": "memory store could not be read"}}

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
        import explain

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
        import sessions

        if not self._course_selected(int(course_id)):
            self._not_found()
            return
        self._send_json(200, {"sessions": sessions.list_sessions(SM_HOME, int(course_id))})

    def _handle_session_detail(self, course_id: str, session_id: str):
        import sessions

        if not self._course_selected(int(course_id)):
            self._not_found()
            return
        detail = sessions.get_session_detail(SM_HOME, int(course_id), session_id)
        if detail is None:
            self._send_json(404, {"error": {"code": "not_found", "message": "no such session"}})
            return
        self._send_json(200, detail)

    def do_POST(self):
        path, _, _ = self.path.partition("?")
        if path == "/config":
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

        if path in ("/github/device/start", "/github/device/poll"):
            # No body is used, but an unread one would be parsed as the
            # next request on a kept-alive connection.
            self.rfile.read(int(self.headers.get("Content-Length", 0)))

        if path == "/github/device/start":
            import github_signin

            try:
                self._send_json(200, github_signin.start())
            except github_signin.SignInError as e:
                self._send_json(503, {"error": {"code": "github_signin_unavailable", "message": str(e)}})
            return

        if path == "/github/device/poll":
            import github_signin

            self._send_json(200, github_signin.poll())
            return

        if path == "/credentials/validate":
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

        unselect_match = UNSELECT_PATH.match(path)
        if unselect_match:
            self._handle_unselect(unselect_match.group(1))
            return

        ask_match = ASK_PATH.match(path)
        if ask_match:
            self._handle_ask(ask_match.group(1))
            return

        sync_match = SYNC_PATH.match(path)
        if sync_match:
            self._handle_course_sync(sync_match.group(1))
            return

        explain_match = EXPLAIN_PATH.match(path)
        if explain_match:
            self._handle_explain(explain_match.group(1), explain_match.group(2))
            return

        session_start_match = SESSION_START_PATH.match(path)
        if session_start_match:
            self._handle_session_start(session_start_match.group(1))
            return

        session_stop_match = SESSION_STOP_PATH.match(path)
        if session_stop_match:
            self._handle_session_stop(session_stop_match.group(1))
            return

        session_notes_match = SESSION_NOTES_PATH.match(path)
        if session_notes_match:
            self._handle_session_notes(session_notes_match.group(1))
            return

        rename_match = SESSION_RENAME_PATH.match(path)
        if rename_match:
            self._handle_session_rename(rename_match.group(1), rename_match.group(2))
            return

        memory_edit_match = MEMORY_EDIT_PATH.match(path)
        if memory_edit_match:
            self._handle_memory_update(memory_edit_match.group(1), memory_edit_match.group(2))
            return

        study_list_match = STUDY_LIST_PATH.match(path)
        if study_list_match:
            self._handle_study_start(study_list_match.group(1))
            return

        study_progress_match = STUDY_PROGRESS_PATH.match(path)
        if study_progress_match:
            self._handle_study_progress(study_progress_match.group(1), study_progress_match.group(2))
            return

        study_export_match = STUDY_EXPORT_PATH.match(path)
        if study_export_match:
            self._handle_study_export(study_export_match.group(1), study_export_match.group(2))
            return

        self._send_json(404, {"error": {"code": "not_found", "message": "no such route"}})

    def do_DELETE(self):
        detail_match = SESSION_DETAIL_PATH.match(self.path)
        if detail_match:
            self._handle_session_delete(detail_match.group(1), detail_match.group(2))
            return
        conversation_match = CONVERSATION_DETAIL_PATH.match(self.path)
        if conversation_match:
            self._handle_conversation_delete(conversation_match.group(1), conversation_match.group(2))
            return
        memory_match = MEMORY_DETAIL_PATH.match(self.path)
        if memory_match:
            self._handle_memory_delete(memory_match.group(1), memory_match.group(2))
            return
        study_match = STUDY_DETAIL_PATH.match(self.path)
        if study_match:
            self._handle_study_delete(study_match.group(1), study_match.group(2))
            return
        course_match = COURSE_PATH.match(self.path)
        if course_match:
            self._handle_delete_course(course_match.group(1))
            return
        self._send_json(404, {"error": {"code": "not_found", "message": "no such route"}})

    def _handle_unselect(self, course_id: str):
        import courses

        if not self._course_selected(int(course_id)):
            self._not_found()
            return
        courses.unselect_course(SM_HOME, int(course_id))
        self._send_json(200, {"status": "unselected"})

    def _handle_delete_course(self, course_id: str):
        import courses

        db_path = SM_HOME / "index.lancedb"
        if not courses.has_local_data(SM_HOME, int(course_id), db_path):
            self._not_found()
            return
        courses.delete_course(SM_HOME, int(course_id), db_path)
        self._send_json(200, {"status": "deleted"})

    def _handle_session_start(self, course_id: str):
        import sessions

        if not self._course_selected(int(course_id)):
            self._not_found()
            return
        self._send_json(200, sessions.start_session(SM_HOME, int(course_id)))

    def _handle_session_stop(self, session_id: str):
        import sessions

        length = int(self.headers.get("Content-Length", 0))
        audio_bytes = self.rfile.read(length)
        try:
            result = sessions.stop_session(session_id, audio_bytes, SM_HOME / "index.lancedb")
        except KeyError:
            self._send_json(404, {"error": {"code": "not_found", "message": "no such session"}})
            return
        self._send_json(200, result)

    def _handle_session_notes(self, session_id: str):
        import sessions

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
        import sessions

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
        import sessions

        if not self._course_selected(int(course_id)):
            self._not_found()
            return
        try:
            sessions.delete_session(SM_HOME, int(course_id), session_id, SM_HOME / "index.lancedb")
        except KeyError:
            self._send_json(404, {"error": {"code": "not_found", "message": "no such session"}})
            return
        self._send_json(200, {"status": "deleted"})

    def _handle_list_conversations(self, course_id: str):
        import conversations

        if not self._course_selected(int(course_id)):
            self._not_found()
            return
        self._send_json(200, {"conversations": conversations.list_conversations(SM_HOME, int(course_id))})

    def _handle_conversation_detail(self, course_id: str, cid: str):
        import conversations

        if not self._course_selected(int(course_id)):
            self._not_found()
            return
        conversation = conversations.get_conversation(SM_HOME, int(course_id), cid)
        if conversation is None:
            self._not_found("no such conversation")
            return
        self._send_json(200, conversation)

    def _handle_conversation_delete(self, course_id: str, cid: str):
        import conversations

        if not self._course_selected(int(course_id)):
            self._not_found()
            return
        try:
            conversations.delete_conversation(SM_HOME, int(course_id), cid)
        except KeyError:
            self._not_found("no such conversation")
            return
        # What memory learned only from this chat goes with it (agent memory
        # design spec §5.7). A job still reading it cleans up after itself
        # (memory_jobs.observe_conversation).
        try:
            with _memory_service(int(course_id)) as service:
                service.forget_conversation(cid)
        except sqlite3.Error as e:
            self._send_json(*self._memory_error(e))
            return
        self._send_json(200, {"status": "deleted"})

    def _handle_list_memories(self, course_id: str, include_inactive: bool):
        if not self._course_selected(int(course_id)):
            self._not_found()
            return
        try:
            with _memory_service(int(course_id)) as service:
                memories = [_memory_json(m) for m in service.list(include_inactive)]
        except sqlite3.Error as e:
            self._send_json(*self._memory_error(e))
            return
        self._send_json(200, {"memories": memories})

    def _handle_memory_delete(self, course_id: str, memory_id: str):
        if not self._course_selected(int(course_id)):
            self._not_found()
            return
        try:
            with _memory_service(int(course_id)) as service:
                deleted = service.forget([memory_id])
        except sqlite3.Error as e:
            self._send_json(*self._memory_error(e))
            return
        if not deleted:
            self._not_found("no such memory")
            return
        self._send_json(200, {"status": "deleted"})

    def _handle_memory_update(self, course_id: str, memory_id: str):
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
        text = data.get("text", "")
        try:
            with _memory_service(int(course_id)) as service:
                updated = service.update_text(memory_id, text)
        except ValueError as e:
            if str(e) == "empty":
                self._send_json(400, {"error": {"code": "bad_request", "message": "memory text cannot be empty"}})
                return
            if str(e) == "inactive":
                self._send_json(409, {"error": {"code": "memory_inactive", "message": "only active memories can be edited"}})
                return
            raise
        except sqlite3.Error as e:
            self._send_json(*self._memory_error(e))
            return
        if updated is None:
            self._not_found("no such memory")
            return
        self._send_json(200, {"memory": _memory_json(updated)})

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
        import chat
        import conversations
        import indexing
        import llm
        from llama_index.vector_stores.lancedb.base import TableNotFoundError
        from memory import compress
        from onnxruntime.capi.onnxruntime_pybind11_state import NoSuchFile as OnnxModelFileMissing

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
        cid = data.get("conversation_id")
        summary = ""
        continuing_conversation = cid is not None
        memory_on = _memory_enabled()
        if cid is None:
            cid = conversations.new_conversation_id()
            try:
                history = chat.parse_history(data.get("history"))
            except ValueError as e:
                self._send_json(400, {"error": {"code": "bad_request", "message": str(e)}})
                return
        else:
            safe = isinstance(cid, str) and SAFE_ID.fullmatch(cid)
            saved = conversations.get_conversation(SM_HOME, int(course_id), cid) if safe else None
            if saved is None:
                self._not_found("no such conversation")
                return
            # The saved chat, not the app's copy of it, which can be stale. A
            # long one goes as its running summary plus its last few turns
            # (agent memory design spec §5.6).
            turns = [{"question": t["question"], "answer": t["answer"]} for t in saved["turns"]]
            if memory_on:
                compressed = compress.build_history(turns, saved["summary"], saved["memory_processed_upto"])
                history, summary = compressed.turns, compressed.summary
            else:
                history, summary = turns, ""
        # No local copy of course names exists (config.json keeps ids only),
        # so the app sends the one it shows in the sidebar.
        course_name = str(data.get("course_name") or "this course")
        asked_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        memory = None
        try:
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
                provider = llm.current_provider()
                memory = _memory_service(int(course_id), provider, conversation_id=cid) if memory_on else None
                events = chat.answer(
                    question,
                    history,
                    course_name,
                    chat.make_search(index, CHAT_SIMILARITY_CUTOFF),
                    provider,
                    memory=memory,
                    summary=summary,
                )
                first = next(events)
            except OnnxModelFileMissing:
                self._send_json(500, {"error": {"code": "model_files_missing", "message": "the local embedding model is missing or corrupted"}})
                return
            except sqlite3.Error as e:
                self._send_json(*self._memory_error(e))
                return
            except LLM_ERRORS as e:
                self._send_json(*self._llm_error(e))
                return
            self._stream_answer(
                int(course_id),
                cid,
                question,
                asked_at,
                memory_on,
                first,
                events,
                create_if_missing=not continuing_conversation,
            )
        finally:
            if memory is not None:
                memory.close()

    def _stream_answer(
        self,
        course_id: int,
        cid: str,
        question: str,
        asked_at: str,
        memory_on: bool,
        first: dict,
        events,
        *,
        create_if_missing: bool,
    ):
        """Streams chat.answer's events, the first one carrying the
        conversation id. A finished answer is saved, and queued for memory,
        before its "done" goes out: the app sends the next question with this
        id as soon as it sees "done", and the chat must exist by then. An
        answer that broke off is neither saved nor remembered."""
        import conversations

        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.send_header("Transfer-Encoding", "chunked")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        answer_parts: list[str] = []
        final: dict = {}
        try:
            for event in itertools.chain([{**first, "conversation_id": cid}], events):
                if "delta" in event:
                    answer_parts.append(event["delta"])
                if "citations" in event:
                    final = event
                if event.get("done"):
                    turn = {
                        "question": question,
                        "answer": "".join(answer_parts),
                        "citations": final.get("citations", []),
                        "grounded": final.get("grounded", False),
                        "asked_at": asked_at,
                    }
                    if conversations.append_turn(
                        SM_HOME, course_id, cid, turn, create_if_missing=create_if_missing
                    ):
                        if memory_on:
                            MEMORY_WORKER.submit((course_id, cid))
                self._write_chunk(event)
        except (BrokenPipeError, ConnectionResetError):
            return  # the app closed the request (student navigated away)
        except Exception as e:
            # Something failed after the answer started streaming (a later
            # search round, or the model connection dropping). The status line
            # is long gone, so the error travels as a stream event instead.
            traceback.print_exc()
            message = self._llm_error(e)[1]["error"]["message"] if isinstance(e, LLM_ERRORS) else "the answer was interrupted"
            self._write_chunk({"error": message})
            self._write_chunk({"done": True})
        self.wfile.write(b"0\r\n\r\n")
        self.wfile.flush()

    def _handle_course_sync(self, course_id: str):
        import course_sync

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
        import explain
        import indexing
        from llama_index.vector_stores.lancedb.base import TableNotFoundError
        from onnxruntime.capi.onnxruntime_pybind11_state import NoSuchFile as OnnxModelFileMissing

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
        except LLM_ERRORS as e:
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

    def _read_json_body(self) -> dict | None:
        """The request's JSON object, or None after answering 400."""
        length = int(self.headers.get("Content-Length", 0))
        try:
            data = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            data = None
        if not isinstance(data, dict):
            self._send_json(400, {"error": {"code": "bad_request", "message": "invalid JSON"}})
            return None
        return data

    def _handle_list_study(self, course_id: str):
        import study

        if not self._course_selected(int(course_id)):
            self._not_found()
            return
        self._send_json(200, {"artifacts": study.list_artifacts(SM_HOME, int(course_id))})

    def _handle_study_sources(self, course_id: str):
        import study

        if not self._course_selected(int(course_id)):
            self._not_found()
            return
        # Canvas's modules give the grouping students know ("Week 02 - ...").
        # Without them (offline, token expired) the list still works, by kind.
        try:
            structure = canvas.get_course_structure(int(course_id))
        except (canvas.CanvasError, httpx.HTTPStatusError, httpx.TransportError):
            structure = None
        self._send_json(200, {"sources": study.list_sources(SM_HOME / "index.lancedb", int(course_id), structure)})

    def _handle_study_detail(self, course_id: str, artifact_id: str):
        import study

        if not self._course_selected(int(course_id)):
            self._not_found()
            return
        artifact = study.get_artifact(SM_HOME, int(course_id), artifact_id)
        if artifact is None:
            self._not_found("no such quiz or deck")
            return
        self._send_json(200, artifact)

    def _handle_study_start(self, course_id: str):
        import llm
        import study

        data = self._read_json_body()
        if data is None:
            return
        if not self._course_selected(int(course_id)):
            self._not_found()
            return
        kind = data.get("kind")
        try:
            options = study.check_options(kind, data)
        except ValueError as e:
            self._send_json(400, {"error": {"code": "bad_request", "message": str(e)}})
            return
        # Fail now on a missing key or unknown provider, not minutes later
        # inside the background run.
        try:
            model = llm.current_provider()
        except LLM_ERRORS as e:
            self._send_json(*self._llm_error(e))
            return

        def embed(text: str) -> list[float]:
            from embeddings import OnnxBgeEmbedding

            return OnnxBgeEmbedding().get_query_embedding(text)

        def describe(e: Exception) -> str:
            if isinstance(e, LLM_ERRORS):
                return self._llm_error(e)[1]["error"]["message"]
            traceback.print_exc()
            return "Something went wrong while writing this. Try again."

        summary = study.start(
            SM_HOME, SM_HOME / "index.lancedb", int(course_id), kind, options, llm=model, embed=embed, describe_error=describe
        )
        self._send_json(202, summary)

    def _handle_study_progress(self, course_id: str, artifact_id: str):
        import study

        data = self._read_json_body()
        if data is None:
            return
        if not self._course_selected(int(course_id)):
            self._not_found()
            return
        progress = data.get("progress") or {}
        if not isinstance(progress, dict):
            self._send_json(400, {"error": {"code": "bad_request", "message": "progress must be an object"}})
            return
        try:
            study.save_progress(SM_HOME, int(course_id), artifact_id, progress)
        except KeyError:
            self._not_found("no such quiz or deck")
            return
        self._send_json(200, {"status": "saved"})

    def _handle_study_export(self, course_id: str, artifact_id: str):
        import study

        length = int(self.headers.get("Content-Length", 0))
        if length:
            self.rfile.read(length)
        if not self._course_selected(int(course_id)):
            self._not_found()
            return
        try:
            path = study.export_csv(SM_HOME, int(course_id), artifact_id, DOWNLOADS_DIR)
        except KeyError:
            self._not_found("no such quiz or deck")
            return
        except OSError as e:
            self._send_json(500, {"error": {"code": "export_failed", "message": f"couldn't save the file: {e.strerror}"}})
            return
        self._send_json(200, {"path": str(path)})

    def _handle_study_delete(self, course_id: str, artifact_id: str):
        import study

        if not self._course_selected(int(course_id)):
            self._not_found()
            return
        study.delete_artifact(SM_HOME, int(course_id), artifact_id)
        self._send_json(200, {"status": "deleted"})

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
    runs, so EOF means the app is gone — quit, crash, or force quit alike.
    Without this the backend outlived the app and kept port 8756, and the
    next launch talked to the stale process. The only thing the app writes
    there is credential updates (credentials.py), one line each."""
    try:
        for line in sys.stdin.buffer:
            if credentials.from_app():
                credentials.receive(line)
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

    # The app writes every stored credential as the first stdin line;
    # waiting for it means no request can see them missing.
    if credentials.from_app() and sys.stdin is not None:
        credentials.receive(sys.stdin.buffer.readline())

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
    threading.Thread(target=queue_startup_memory_jobs, name="startup-memory", daemon=True).start()
    server.serve_forever()
