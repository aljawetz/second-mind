"""Replays real captured Canvas responses (tests/fixtures/canvas/) — no live
Canvas access needed to run these. See implementation-plan.md Step 3."""

import json
from pathlib import Path

import httpx
import pytest
import respx

import canvas
import config

FIXTURES = Path(__file__).parent / "fixtures" / "canvas"
BASE = canvas.CANVAS_API_URL


def load(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text())


@pytest.fixture(autouse=True)
def fake_token(monkeypatch):
    monkeypatch.setattr(canvas.keyring, "get_password", lambda service, key: "fake-token-for-tests")


@pytest.fixture(autouse=True)
def fake_ssb_home(tmp_path, monkeypatch):
    # No config.json here — real isolation from whatever's on the actual
    # dev machine, and _api_base() falls through to CANVAS_API_URL (BASE
    # above), same as every test already assumes.
    monkeypatch.setattr(canvas, "SSB_HOME", tmp_path)


@respx.mock
def test_list_courses():
    fx = load("courses")
    respx.get(f"{BASE}/courses").mock(return_value=httpx.Response(fx["status"], json=fx["body"]))
    courses = canvas.list_courses()
    assert len(courses) == len(fx["body"])
    assert courses[0]["id"] == fx["body"][0]["id"]


@respx.mock
def test_get_page():
    fx = load("page")
    respx.get(f"{BASE}/courses/51113/pages/academic-integrity-and-credibility").mock(
        return_value=httpx.Response(fx["status"], json=fx["body"])
    )
    page = canvas.get_page(51113, "academic-integrity-and-credibility")
    assert page["title"] == fx["body"]["title"]


@respx.mock
def test_get_assignment():
    fx = load("assignment")
    respx.get(f"{BASE}/courses/56350/assignments/1020612").mock(
        return_value=httpx.Response(fx["status"], json=fx["body"])
    )
    a = canvas.get_assignment(56350, 1020612)
    assert a["name"] == fx["body"]["name"]


@respx.mock
def test_course_structure_success():
    fx = load("course_structure_ok")
    respx.get(f"{BASE}/courses/55710/modules").mock(return_value=httpx.Response(fx["status"], json=fx["body"]))
    modules = canvas.get_course_structure(55710)
    assert len(modules) == len(fx["body"])


@respx.mock
def test_course_structure_403_degrades_to_empty():
    """canvas-integration.md §2: get_course_structure can 403 for an entire
    course/section — real case, course 55709 (one of the two 18654-SV IDs)."""
    fx = load("course_structure_403")
    respx.get(f"{BASE}/courses/55709/modules").mock(return_value=httpx.Response(fx["status"], json=fx["body"]))
    modules = canvas.get_course_structure(55709)
    assert modules == []


@respx.mock
def test_configured_base_url_is_used_instead_of_default(tmp_path, monkeypatch):
    """contribution-and-distribution-plan.md step 2 — a school other than
    CMU must actually be reachable, not just accepted by onboarding."""
    monkeypatch.setattr(canvas, "SSB_HOME", tmp_path)
    config.write_config(tmp_path, {"canvas_base_url": "https://canvas.instructure.com"})
    fx = load("courses")
    respx.get("https://canvas.instructure.com/api/v1/courses").mock(
        return_value=httpx.Response(fx["status"], json=fx["body"])
    )
    result = canvas.list_courses()
    assert len(result) == len(fx["body"])


@respx.mock
def test_list_course_files_403_degrades_to_empty():
    """canvas-integration.md §2: the bulk Files-tab listing 403s under a
    student token — real case, course 56350."""
    fx = load("list_course_files_403")
    respx.get(f"{BASE}/courses/56350/files").mock(return_value=httpx.Response(fx["status"], json=fx["body"]))
    files = canvas.list_course_files(56350)
    assert files == []


# --- Retries on transient failures -------------------------------------------
# A real sync lost a file to one "_ssl.c: The handshake operation timed out"
# on get_file; the same request succeeded moments later.


@pytest.fixture
def no_sleep(monkeypatch):
    slept = []
    monkeypatch.setattr(canvas.time, "sleep", slept.append)
    return slept


@respx.mock
def test_transport_error_is_retried_then_succeeds(no_sleep):
    route = respx.get(f"{BASE}/files/1").mock(
        side_effect=[httpx.ConnectTimeout("handshake timed out"), httpx.Response(200, json={"id": 1})]
    )
    assert canvas.get_file(1) == {"id": 1}
    assert route.call_count == 2
    assert no_sleep == [1]


@respx.mock
def test_server_error_is_retried_then_succeeds(no_sleep):
    route = respx.get(f"{BASE}/files/1").mock(side_effect=[httpx.Response(503), httpx.Response(200, json={"id": 1})])
    assert canvas.get_file(1) == {"id": 1}
    assert route.call_count == 2


@respx.mock
def test_persistent_transport_error_raises_after_three_attempts(no_sleep):
    route = respx.get(f"{BASE}/files/1").mock(side_effect=httpx.ReadTimeout("timed out"))
    with pytest.raises(httpx.ReadTimeout):
        canvas.get_file(1)
    assert route.call_count == 3


@respx.mock
def test_persistent_server_error_raises_after_three_attempts(no_sleep):
    route = respx.get(f"{BASE}/files/1").mock(return_value=httpx.Response(502))
    with pytest.raises(httpx.HTTPStatusError):
        canvas.get_file(1)
    assert route.call_count == 3


@respx.mock
def test_403_is_not_retried(no_sleep):
    route = respx.get(f"{BASE}/files/1").mock(return_value=httpx.Response(403))
    assert canvas.get_file(1) is None
    assert route.call_count == 1 and no_sleep == []


@respx.mock
def test_download_follows_redirect_and_retries_transport_errors(no_sleep):
    respx.get("https://canvas.example/files/9/download").mock(
        side_effect=[
            httpx.ConnectError("reset"),
            httpx.Response(302, headers={"location": "https://storage.example/f9.pdf"}),
        ]
    )
    respx.get("https://storage.example/f9.pdf").mock(return_value=httpx.Response(200, content=b"%PDF-1.7"))
    assert canvas.download("https://canvas.example/files/9/download") == b"%PDF-1.7"


@respx.mock
def test_download_raises_on_an_error_status_instead_of_returning_the_error_page(no_sleep):
    # The old httpx.get call never checked the status: a 403 HTML page would
    # have been written to disk and handed to the PDF extractor.
    respx.get("https://canvas.example/files/9/download").mock(return_value=httpx.Response(403, text="<html>denied</html>"))
    with pytest.raises(httpx.HTTPStatusError):
        canvas.download("https://canvas.example/files/9/download")
