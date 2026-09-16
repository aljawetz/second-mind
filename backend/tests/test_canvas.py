"""Replays real captured Canvas responses (tests/fixtures/canvas/) — no live
Canvas access needed to run these. See implementation-plan.md Step 3."""

import json
from pathlib import Path

import httpx
import pytest
import respx

import canvas

FIXTURES = Path(__file__).parent / "fixtures" / "canvas"
BASE = canvas.CANVAS_API_URL


def load(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text())


@pytest.fixture(autouse=True)
def fake_token(monkeypatch):
    monkeypatch.setattr(canvas.keyring, "get_password", lambda service, key: "fake-token-for-tests")


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
def test_list_course_files_403_degrades_to_empty():
    """canvas-integration.md §2: the bulk Files-tab listing 403s under a
    student token — real case, course 56350."""
    fx = load("list_course_files_403")
    respx.get(f"{BASE}/courses/56350/files").mock(return_value=httpx.Response(fx["status"], json=fx["body"]))
    files = canvas.list_course_files(56350)
    assert files == []
