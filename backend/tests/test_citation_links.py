"""citation_links.canvas_url: the Canvas page a search result cites, built
the same way the app's app/src/citations.ts builds it, so a citation in
Claude Code opens the same page a citation in the app does."""

import pytest

import citation_links

ORIGIN = "https://canvas.example.edu"


@pytest.mark.parametrize(
    "item_type, item_id, url",
    [
        ("file", "file:14690029", f"{ORIGIN}/courses/56350/files/14690029"),
        ("page", "page:week-1-overview", f"{ORIGIN}/courses/56350/pages/week-1-overview"),
        ("assignment", "assignment:1020612", f"{ORIGIN}/courses/56350/assignments/1020612"),
        ("syllabus", "syllabus:56350", f"{ORIGIN}/courses/56350/assignments/syllabus"),
        (None, "file:7", f"{ORIGIN}/courses/56350/files/7"),  # citations.ts treats an unknown type as a file
    ],
)
def test_canvas_url_matches_the_app(item_type, item_id, url):
    assert citation_links.canvas_url(ORIGIN, 56350, item_type, item_id) == url


@pytest.mark.parametrize("item_type", ["transcript", "notes"])
def test_class_recordings_have_no_canvas_page(item_type):
    assert citation_links.canvas_url(ORIGIN, 56350, item_type, "2026-09-29-class-1") is None


def test_no_id_means_no_link():
    assert citation_links.canvas_url(ORIGIN, 56350, "file", "") is None


def test_origin_comes_from_config_and_is_normalized(tmp_path):
    (tmp_path / "config.json").write_text('{"canvas_base_url": "canvas.example.edu/api/v1/"}')

    assert citation_links.canvas_origin(tmp_path) == ORIGIN


def test_origin_defaults_like_canvas_py(tmp_path):
    assert citation_links.canvas_origin(tmp_path) == "https://canvas.cmu.edu"


def test_origin_from_the_plugin_env_wins(tmp_path, monkeypatch):
    (tmp_path / "config.json").write_text('{"canvas_base_url": "https://other.example.edu"}')
    monkeypatch.setenv("SM_CANVAS_URL", "https://canvas.example.edu/")

    assert citation_links.canvas_origin(tmp_path) == ORIGIN
