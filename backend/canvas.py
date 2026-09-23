"""Direct Canvas REST API client — implementation-plan.md Step 3.

Bearer-token auth with the student's own Canvas token, read from Keychain
per call (cheap lookup; picks up a re-entered key immediately, no caching
staleness). Pagination follows the Link response header (RFC 5988) —
confirmed against a real request before writing this, not assumed.

A 403/404 on any individual endpoint means "not available to this token" and
degrades to an empty result rather than raising — canvas-integration.md §2/§4.
A 429 means rate-limited and gets retried with backoff — §5.
"""

import re
import time
from pathlib import Path

import httpx
import keyring

import config

# Default when nothing's configured yet — real base URL is a config.json
# value (contribution-and-distribution-plan.md step 2), not a constant;
# SSB used to only work against CMU's Canvas at all.
CANVAS_API_URL = "https://canvas.cmu.edu/api/v1"
CREDENTIAL_SERVICE = "com.ssb.app"
SSB_HOME = Path.home() / ".ssb"  # set to the real value by main.py at startup; tests monkeypatch this directly

_LINK_RE = re.compile(r'<([^>]+)>;\s*rel="([^"]+)"')


class CanvasError(Exception):
    """A Canvas API failure that isn't a recoverable 403/404 or 429."""


def _token() -> str:
    token = keyring.get_password(CREDENTIAL_SERVICE, "canvas-token")
    if not token:
        raise CanvasError("no Canvas token stored — onboarding hasn't completed")
    return token


def _api_base() -> str:
    origin = config.read_config(SSB_HOME).get("canvas_base_url")
    return f"{origin}/api/v1" if origin else CANVAS_API_URL


def _client() -> httpx.Client:
    return httpx.Client(
        base_url=_api_base(),
        headers={"Authorization": f"Bearer {_token()}"},
        timeout=15.0,
    )


def _next_link(link_header: str | None) -> str | None:
    if not link_header:
        return None
    for url, rel in _LINK_RE.findall(link_header):
        if rel == "next":
            return url
    return None


def _get(client: httpx.Client, url: str, params: dict | None = None, max_retries: int = 3) -> httpx.Response | None:
    """GET with 429 backoff; 403/404 returns None (not available)."""
    for attempt in range(max_retries):
        r = client.get(url, params=params)
        if r.status_code == 429:
            wait = float(r.headers.get("Retry-After", 2**attempt))
            time.sleep(wait)
            continue
        if r.status_code in (403, 404):
            return None
        r.raise_for_status()
        return r
    raise CanvasError(f"rate limited after {max_retries} retries: {url}")


def _get_all(client: httpx.Client, path: str, params: dict | None = None) -> list:
    """Follow Link-header pagination across every page. A 403/404 on the
    endpoint itself degrades to [] rather than raising — canvas-integration.md
    §2 (a 403 here isn't distinguishable from "genuinely empty" without a
    logging layer we don't have yet; both degrade the same way for now)."""
    items: list = []
    url = path
    first = True
    while url:
        r = _get(client, url, params=params if first else None)
        first = False
        if r is None:
            return items
        items.extend(r.json())
        url = _next_link(r.headers.get("link"))
    return items


def list_courses() -> list[dict]:
    with _client() as client:
        return _get_all(client, "/courses", params={"per_page": 50})


def list_assignments(course_id: int) -> list[dict]:
    # include[]=submission embeds the student's own real submission status
    # (workflow_state, submitted_at, late, missing) directly in each
    # assignment — confirmed against a real course, avoids an N+1 call per
    # assignment to /submissions/self.
    with _client() as client:
        return _get_all(client, f"/courses/{course_id}/assignments", params={"per_page": 50, "include[]": "submission"})


def get_assignment(course_id: int, assignment_id: int) -> dict | None:
    with _client() as client:
        r = _get(client, f"/courses/{course_id}/assignments/{assignment_id}")
        return r.json() if r else None


def list_pages(course_id: int) -> list[dict]:
    with _client() as client:
        return _get_all(client, f"/courses/{course_id}/pages", params={"per_page": 50})


def get_page(course_id: int, page_url: str) -> dict | None:
    with _client() as client:
        r = _get(client, f"/courses/{course_id}/pages/{page_url}")
        return r.json() if r else None


def get_front_page(course_id: int) -> dict | None:
    """The course home page, when the course uses a wiki page as its home
    — a regular page (url slug, body, updated_at), often not in Modules.
    None (404) for courses whose home is Modules or the syllabus."""
    with _client() as client:
        r = _get(client, f"/courses/{course_id}/front_page")
        return r.json() if r else None


def get_syllabus(course_id: int) -> str | None:
    """syllabus_body HTML — where due dates and grading rules live. Not a
    wiki page and has no updated_at of its own; course_sync.py diffs it by
    content hash instead."""
    with _client() as client:
        r = _get(client, f"/courses/{course_id}", params={"include[]": "syllabus_body"})
        return r.json().get("syllabus_body") if r else None


def get_course_structure(course_id: int) -> list[dict]:
    """Modules + items — navigation metadata and the file-discovery path
    (list_course_files 403s under a student token; individual files stay
    reachable via module items of type File, fetched by content_id)."""
    with _client() as client:
        return _get_all(
            client,
            f"/courses/{course_id}/modules",
            params={"include[]": "items", "per_page": 50},
        )


def list_course_files(course_id: int) -> list[dict]:
    """The bulk Files-tab listing — known to 403 under a student token
    (canvas-integration.md §2). Not used for real file discovery (that's
    get_course_structure + get_file below); kept so the known failure mode
    has real code and a real fixture to test against."""
    with _client() as client:
        return _get_all(client, f"/courses/{course_id}/files", params={"per_page": 50})


def get_file(file_id: int) -> dict | None:
    """A single file's metadata (incl. download URL), by the content_id
    found via get_course_structure's module items."""
    with _client() as client:
        r = _get(client, f"/files/{file_id}")
        return r.json() if r else None
