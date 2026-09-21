"""course_sync.py — docs/superpowers/specs/2026-09-20-course-sync-phase1-design.md.

canvas.py, ingestion.py, and indexing.py are all monkeypatched with plain
stubs here — this tests course_sync.py's own branching logic
(new/changed/deleted/failed), not Canvas's real API shape or real
extraction/embedding, which their own test suites already cover. The
real, unmocked end-to-end proof against live Canvas is
scripts/course_sync_smoke_test.py.
"""

import pytest

import course_sync

FILE_META = {
    "id": 111,
    "display_name": "syllabus.pdf",
    "updated_at": "2026-01-01",
    "url": "https://canvas.example/files/111",
}
PAGE_SUMMARY = {"url": "week-1-overview", "title": "Week 1 Overview", "updated_at": "2026-01-01"}


def _structure_with_one_file():
    return [{"items": [{"type": "File", "content_id": FILE_META["id"]}]}]


@pytest.fixture
def stub_canvas(monkeypatch):
    monkeypatch.setattr(course_sync.canvas, "get_course_structure", lambda course_id: _structure_with_one_file())
    monkeypatch.setattr(course_sync.canvas, "get_file", lambda file_id: dict(FILE_META))
    monkeypatch.setattr(course_sync.canvas, "list_pages", lambda course_id: [dict(PAGE_SUMMARY)])
    monkeypatch.setattr(
        course_sync.canvas, "get_page", lambda course_id, url: {"title": PAGE_SUMMARY["title"], "body": "<p>hello</p>"}
    )


@pytest.fixture
def stub_extraction(monkeypatch):
    monkeypatch.setattr(course_sync.httpx, "get", lambda *a, **k: type("R", (), {"content": b"raw bytes"})())
    monkeypatch.setattr(
        course_sync.ingestion,
        "extract_pdf",
        lambda path: [{"page": 1, "text": "syllabus content", "char_count": 17, "has_image": False, "needs_fallback": False}],
    )
    monkeypatch.setattr(
        course_sync.ingestion,
        "extract_pptx",
        lambda path: [{"slide": 1, "text": "slide content", "char_count": 13, "has_image": False}],
    )
    monkeypatch.setattr(course_sync.ingestion, "extract_html_page", lambda html: "page content")
    monkeypatch.setattr(course_sync.indexing, "add_nodes", lambda nodes, db_path, table_name: None)
    monkeypatch.setattr(course_sync.indexing, "delete_ref_doc_nodes", lambda db_path, table_name, ref_doc_id: None)


def run(course_id, ssb_home):
    return list(course_sync.sync_course(course_id, ssb_home))


def test_first_sync_reports_one_new_file_and_one_new_page(tmp_path, stub_canvas, stub_extraction):
    events = run(1, tmp_path)
    assert events[-1] == {"done": True, "new": 2, "changed": 0, "removed": 0, "failed": 0}
    done_items = {e["item"] for e in events if e.get("status") == "done"}
    assert done_items == {"syllabus.pdf", "Week 1 Overview"}


def test_second_sync_with_no_remote_changes_reports_nothing(tmp_path, stub_canvas, stub_extraction):
    run(1, tmp_path)
    events = run(1, tmp_path)
    assert events == [{"done": True, "new": 0, "changed": 0, "removed": 0, "failed": 0}]


def test_changed_file_is_resynced(tmp_path, stub_canvas, stub_extraction, monkeypatch):
    run(1, tmp_path)
    monkeypatch.setattr(course_sync.canvas, "get_file", lambda file_id: dict(FILE_META, updated_at="2026-02-01"))
    events = run(1, tmp_path)
    assert events[-1] == {"done": True, "new": 0, "changed": 1, "removed": 0, "failed": 0}


def test_removed_items_are_deleted_from_index_and_manifest(tmp_path, stub_canvas, stub_extraction, monkeypatch):
    run(1, tmp_path)
    monkeypatch.setattr(course_sync.canvas, "get_course_structure", lambda course_id: [])
    monkeypatch.setattr(course_sync.canvas, "list_pages", lambda course_id: [])
    events = run(1, tmp_path)
    assert events[-1] == {"done": True, "new": 0, "changed": 0, "removed": 2, "failed": 0}


def test_one_failing_item_does_not_abort_the_rest(tmp_path, stub_canvas, monkeypatch):
    monkeypatch.setattr(course_sync.httpx, "get", lambda *a, **k: type("R", (), {"content": b"raw bytes"})())
    monkeypatch.setattr(
        course_sync.ingestion, "extract_pdf", lambda path: (_ for _ in ()).throw(RuntimeError("corrupt pdf"))
    )
    monkeypatch.setattr(course_sync.ingestion, "extract_html_page", lambda html: "page content")
    monkeypatch.setattr(course_sync.indexing, "add_nodes", lambda nodes, db_path, table_name: None)
    monkeypatch.setattr(course_sync.indexing, "delete_ref_doc_nodes", lambda db_path, table_name, ref_doc_id: None)
    events = run(1, tmp_path)
    assert events[-1] == {"done": True, "new": 1, "changed": 0, "removed": 0, "failed": 1}
    failed = [e for e in events if e.get("status") == "failed"]
    assert len(failed) == 1
    assert failed[0]["error"] == "corrupt pdf"


def test_whole_course_failure_yields_a_single_error_event(tmp_path, monkeypatch):
    def raise_canvas_error(course_id):
        raise course_sync.canvas.CanvasError("token expired")

    monkeypatch.setattr(course_sync.canvas, "get_course_structure", raise_canvas_error)
    events = run(1, tmp_path)
    assert events == [{"done": True, "error": "token expired"}]
