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
