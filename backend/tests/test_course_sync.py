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

FILE_META_2 = {
    "id": 222,
    "display_name": "lecture.pdf",
    "updated_at": "2026-01-01",
    "url": "https://canvas.example/files/222",
}
PAGE_SUMMARY_2 = {"url": "week-2-overview", "title": "Week 2 Overview", "updated_at": "2026-01-01"}


def _structure_with_one_file():
    return [{"items": [{"type": "File", "content_id": FILE_META["id"]}]}]


def _structure(*metas):
    return [{"items": [{"type": "File", "content_id": m["id"]} for m in metas]}]


def _manifest_ids(ssb_home, course_id=1):
    """Reads the real manifest.db the sync just wrote — deletion guards are
    about what survives on disk, not only about the emitted counts."""
    conn = course_sync.sync.open_manifest(ssb_home / "courses" / str(course_id) / "manifest.db")
    try:
        return {row[0] for row in conn.execute("SELECT canvas_item_id FROM manifest").fetchall()}
    finally:
        conn.close()


@pytest.fixture(autouse=True)
def no_front_page_or_syllabus(monkeypatch):
    """Every test here stubs canvas per function; these two default to
    "course has neither" so no test can reach real Canvas through them.
    Tests about front pages or syllabi override them."""
    monkeypatch.setattr(course_sync.canvas, "get_front_page", lambda course_id: None)
    monkeypatch.setattr(course_sync.canvas, "get_syllabus", lambda course_id: None)


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
    """Returns the shared `calls` list so tests can assert on indexing
    call order/arguments (delete-before-add on a changed item, exactly
    which ref_doc_ids got deleted) instead of only trusting the final
    new/changed/removed counts."""
    calls = []
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
    monkeypatch.setattr(
        course_sync.indexing,
        "add_nodes",
        lambda nodes, db_path, table_name: calls.append(("add", table_name, len(nodes))),
    )
    monkeypatch.setattr(
        course_sync.indexing,
        "delete_ref_doc_nodes",
        lambda db_path, table_name, ref_doc_id: calls.append(("delete", table_name, ref_doc_id)),
    )
    return calls


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
    baseline = len(stub_extraction)  # first sync's own add calls shouldn't be mistaken for the second sync's
    monkeypatch.setattr(course_sync.canvas, "get_file", lambda file_id: dict(FILE_META, updated_at="2026-02-01"))
    events = run(1, tmp_path)
    assert events[-1] == {"done": True, "new": 0, "changed": 1, "removed": 0, "failed": 0}

    # Delete-before-add is the plan's most-emphasized ordering constraint
    # for a changed item — verify it actually happened, not just that the
    # final counts say "changed: 1".
    new_calls = stub_extraction[baseline:]
    assert ("delete", "course_1", "file:111") in new_calls
    delete_pos = new_calls.index(("delete", "course_1", "file:111"))
    add_positions = [i for i, c in enumerate(new_calls) if c[0] == "add"]
    assert add_positions, "expected at least one add call for the re-synced file"
    assert delete_pos < add_positions[0]


def test_removed_items_are_deleted_from_index_and_manifest(tmp_path, stub_extraction, monkeypatch):
    """An item missing from a listing that still returned *other* items is
    real evidence of deletion — unlike the wholly-empty listing covered by
    test_empty_listing_after_a_prior_sync_deletes_nothing below."""
    metas = {m["id"]: m for m in (FILE_META, FILE_META_2)}
    monkeypatch.setattr(course_sync.canvas, "get_course_structure", lambda course_id: _structure(FILE_META, FILE_META_2))
    monkeypatch.setattr(course_sync.canvas, "get_file", lambda file_id: dict(metas[file_id]))
    monkeypatch.setattr(course_sync.canvas, "list_pages", lambda course_id: [dict(PAGE_SUMMARY), dict(PAGE_SUMMARY_2)])
    monkeypatch.setattr(course_sync.canvas, "get_page", lambda course_id, url: {"body": "<p>hello</p>"})

    run(1, tmp_path)
    baseline = len(stub_extraction)

    # Second round: one file and one page dropped off, the others remain.
    monkeypatch.setattr(course_sync.canvas, "get_course_structure", lambda course_id: _structure(FILE_META))
    monkeypatch.setattr(course_sync.canvas, "list_pages", lambda course_id: [dict(PAGE_SUMMARY)])
    events = run(1, tmp_path)
    assert events[-1] == {"done": True, "new": 0, "changed": 0, "removed": 2, "failed": 0}

    deleted_ref_doc_ids = {c[2] for c in stub_extraction[baseline:] if c[0] == "delete"}
    assert deleted_ref_doc_ids == {"file:222", "page:week-2-overview"}
    assert _manifest_ids(tmp_path) == {"file:111", "page:week-1-overview"}


def test_empty_listing_after_a_prior_sync_deletes_nothing(tmp_path, stub_canvas, stub_extraction, monkeypatch):
    """canvas.py degrades a 403/404 to an empty list, so a course whose
    modules/pages got hidden or locked is indistinguishable from a course
    with genuinely zero items. Deleting on that signal would silently wipe
    the whole indexed corpus, so an empty listing must delete nothing."""
    run(1, tmp_path)
    baseline = len(stub_extraction)
    monkeypatch.setattr(course_sync.canvas, "get_course_structure", lambda course_id: [])
    monkeypatch.setattr(course_sync.canvas, "list_pages", lambda course_id: [])

    events = run(1, tmp_path)

    assert events == [{"done": True, "new": 0, "changed": 0, "removed": 0, "failed": 0}]
    assert [c for c in stub_extraction[baseline:] if c[0] == "delete"] == []
    assert _manifest_ids(tmp_path) == {"file:111", "page:week-1-overview"}


def test_file_whose_metadata_fetch_degrades_to_none_is_not_deleted(tmp_path, stub_extraction, monkeypatch):
    """A 403/404 on one specific file (canvas.get_file returning None) is
    the same ambiguous signal as a 403 on the whole listing — that file
    must keep its index/manifest entry, while the files around it in the
    same listing keep syncing normally."""
    metas = {m["id"]: m for m in (FILE_META, FILE_META_2)}
    monkeypatch.setattr(course_sync.canvas, "get_course_structure", lambda course_id: _structure(FILE_META, FILE_META_2))
    monkeypatch.setattr(course_sync.canvas, "get_file", lambda file_id: dict(metas[file_id]))
    monkeypatch.setattr(course_sync.canvas, "list_pages", lambda course_id: [dict(PAGE_SUMMARY)])
    monkeypatch.setattr(course_sync.canvas, "get_page", lambda course_id, url: {"body": "<p>hello</p>"})

    events = run(1, tmp_path)
    assert events[-1] == {"done": True, "new": 3, "changed": 0, "removed": 0, "failed": 0}
    baseline = len(stub_extraction)

    # Second round: file 222 now 403s (None, no exception raised), and
    # file 111 has genuinely changed upstream.
    def get_file(file_id):
        if file_id == 222:
            return None
        return dict(FILE_META, updated_at="2026-02-01")

    monkeypatch.setattr(course_sync.canvas, "get_file", get_file)
    events = run(1, tmp_path)

    # The still-resolvable file re-syncs; nothing is reported removed.
    assert events[-1] == {"done": True, "new": 0, "changed": 1, "removed": 0, "failed": 0}
    new_calls = stub_extraction[baseline:]
    deleted_ref_doc_ids = {c[2] for c in new_calls if c[0] == "delete"}
    assert "file:222" not in deleted_ref_doc_ids  # its indexed chunks survive
    assert deleted_ref_doc_ids == {"file:111"}  # only the changed file's own delete-before-add
    assert [c for c in new_calls if c[0] == "add"], "the still-resolvable file should have been re-indexed"
    assert _manifest_ids(tmp_path) == {"file:111", "file:222", "page:week-1-overview"}


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


def test_unexpected_mid_sync_failure_still_yields_a_terminal_event(tmp_path, stub_canvas, stub_extraction, monkeypatch):
    """main.py has already sent the 200 and streaming headers before this
    generator's body runs, so an exception escaping mid-stream would kill
    the connection with no terminating event and leave the frontend stuck
    waiting forever. Something outside the per-item try/excepts blowing up
    (here: the manifest diff) must still produce a terminal event."""

    def boom(conn, item_type, remote_items):
        raise RuntimeError("manifest exploded")

    monkeypatch.setattr(course_sync.sync, "diff", boom)

    events = run(1, tmp_path)

    assert events == [{"done": True, "error": "manifest exploded"}]


def test_get_file_failure_does_not_abort_the_rest(tmp_path, stub_extraction, monkeypatch):
    """A single item.canvas.get_file() failure during metadata collection
    (a real Canvas/network error, distinct from the extraction failures
    covered by test_one_failing_item_does_not_abort_the_rest) must be
    isolated the same way — it should not escape the generator and abort
    the whole course sync."""

    def structure_two_files(course_id):
        return [{"items": [{"type": "File", "content_id": 111}, {"type": "File", "content_id": 222}]}]

    def get_file(file_id):
        if file_id == 222:
            raise course_sync.canvas.CanvasError("file gone")
        return dict(FILE_META)

    monkeypatch.setattr(course_sync.canvas, "get_course_structure", structure_two_files)
    monkeypatch.setattr(course_sync.canvas, "get_file", get_file)
    monkeypatch.setattr(course_sync.canvas, "list_pages", lambda course_id: [])

    events = run(1, tmp_path)

    assert events[-1] == {"done": True, "new": 1, "changed": 0, "removed": 0, "failed": 1}
    failed = [e for e in events if e.get("status") == "failed"]
    assert failed == [{"item": "222", "status": "failed", "error": "file gone"}]
    done_items = {e["item"] for e in events if e.get("status") == "done"}
    assert done_items == {"syllabus.pdf"}


def test_unsupported_file_extension_is_skipped_not_synced(tmp_path, stub_extraction, monkeypatch, capsys):
    def structure_with_docx(course_id):
        return [{"items": [{"type": "File", "content_id": 333}]}]

    monkeypatch.setattr(course_sync.canvas, "get_course_structure", structure_with_docx)
    monkeypatch.setattr(
        course_sync.canvas,
        "get_file",
        lambda file_id: {"id": 333, "display_name": "notes.docx", "updated_at": "2026-01-01", "url": "https://canvas.example/files/333"},
    )
    monkeypatch.setattr(course_sync.canvas, "list_pages", lambda course_id: [])

    events = run(1, tmp_path)

    assert events == [{"done": True, "new": 0, "changed": 0, "removed": 0, "failed": 0}]
    assert "notes.docx" in capsys.readouterr().out


# --- Pages from Modules / front page / syllabus -----------------------------
# Real data behind these: the Pages-tab listing 404s for students in 8 of 10
# surveyed courses, while every module Page item opened individually (211 of
# 211) — five courses had no other content, so a sync indexed nothing.


def _module_pages(*urls):
    return [{"items": [{"type": "Page", "page_url": u, "title": u} for u in urls]}]


def _full_page(url, updated_at="2026-01-01"):
    return {"url": url, "title": url.replace("-", " ").title(), "updated_at": updated_at, "body": f"<p>{url}</p>"}


@pytest.fixture
def module_pages_only(monkeypatch):
    """A course like 55016: pages list 404s (empty), content is Page items
    in Modules. Returns the list of get_page calls made."""
    fetched = []

    def get_page(course_id, url):
        fetched.append(url)
        return _full_page(url)

    monkeypatch.setattr(course_sync.canvas, "get_course_structure", lambda course_id: _module_pages("intro", "week-1"))
    monkeypatch.setattr(course_sync.canvas, "list_pages", lambda course_id: [])
    monkeypatch.setattr(course_sync.canvas, "get_page", get_page)
    return fetched


def test_module_page_items_are_indexed_when_the_pages_list_404s(tmp_path, stub_extraction, module_pages_only):
    events = run(1, tmp_path)

    assert events[-1] == {"done": True, "new": 2, "changed": 0, "removed": 0, "failed": 0}
    assert {e["item"] for e in events if e.get("status") == "done"} == {"Intro", "Week 1"}
    assert _manifest_ids(tmp_path) == {"page:intro", "page:week-1"}
    # Fetched once each while listing; _sync_page reuses that body.
    assert module_pages_only == ["intro", "week-1"]


def test_unchanged_module_pages_are_not_reindexed(tmp_path, stub_extraction, module_pages_only):
    run(1, tmp_path)
    baseline = len(stub_extraction)

    events = run(1, tmp_path)

    assert events == [{"done": True, "new": 0, "changed": 0, "removed": 0, "failed": 0}]
    assert stub_extraction[baseline:] == []


def test_an_edited_module_page_is_resynced(tmp_path, stub_extraction, module_pages_only, monkeypatch):
    run(1, tmp_path)
    baseline = len(stub_extraction)
    monkeypatch.setattr(
        course_sync.canvas, "get_page", lambda course_id, url: _full_page(url, "2026-02-01" if url == "intro" else "2026-01-01")
    )

    events = run(1, tmp_path)

    assert events[-1] == {"done": True, "new": 0, "changed": 1, "removed": 0, "failed": 0}
    assert [c for c in stub_extraction[baseline:] if c[0] == "delete"] == [("delete", "course_1", "page:intro")]


def test_a_page_in_both_the_pages_list_and_modules_is_indexed_once(tmp_path, stub_extraction, monkeypatch):
    fetched = []
    monkeypatch.setattr(course_sync.canvas, "get_course_structure", lambda course_id: _module_pages(PAGE_SUMMARY["url"]))
    monkeypatch.setattr(course_sync.canvas, "list_pages", lambda course_id: [dict(PAGE_SUMMARY)])
    monkeypatch.setattr(
        course_sync.canvas, "get_page", lambda course_id, url: fetched.append(url) or {"title": "Week 1 Overview", "body": "<p>x</p>"}
    )

    events = run(1, tmp_path)

    assert events[-1]["new"] == 1
    assert _manifest_ids(tmp_path) == {"page:week-1-overview"}
    assert fetched == ["week-1-overview"]  # only _sync_page's fetch — a listed summary has no body


def test_the_front_page_is_indexed_and_deduped_with_modules(tmp_path, stub_extraction, module_pages_only, monkeypatch):
    monkeypatch.setattr(course_sync.canvas, "get_front_page", lambda course_id: _full_page("welcome"))
    monkeypatch.setattr(course_sync.canvas, "get_course_structure", lambda course_id: _module_pages("welcome", "week-1"))

    events = run(1, tmp_path)

    assert events[-1]["new"] == 2
    assert _manifest_ids(tmp_path) == {"page:welcome", "page:week-1"}
    assert module_pages_only == ["week-1"]  # the front page body was already in hand


def test_a_module_page_that_404s_is_not_deleted(tmp_path, stub_extraction, module_pages_only, monkeypatch):
    run(1, tmp_path)
    baseline = len(stub_extraction)
    monkeypatch.setattr(course_sync.canvas, "get_page", lambda course_id, url: None if url == "intro" else _full_page(url))

    events = run(1, tmp_path)

    assert events[-1] == {"done": True, "new": 0, "changed": 0, "removed": 0, "failed": 0}
    assert [c for c in stub_extraction[baseline:] if c[0] == "delete"] == []
    assert _manifest_ids(tmp_path) == {"page:intro", "page:week-1"}


def test_a_module_page_fetch_error_fails_that_page_only(tmp_path, stub_extraction, module_pages_only, monkeypatch):
    run(1, tmp_path)

    def get_page(course_id, url):
        if url == "intro":
            raise RuntimeError("handshake timed out")
        return _full_page(url, "2026-02-01")

    monkeypatch.setattr(course_sync.canvas, "get_page", get_page)
    events = run(1, tmp_path)

    assert events[-1] == {"done": True, "new": 0, "changed": 1, "removed": 0, "failed": 1}
    assert {"item": "intro", "status": "failed", "error": "handshake timed out"} in events
    assert _manifest_ids(tmp_path) == {"page:intro", "page:week-1"}


def test_syllabus_is_indexed_then_resynced_only_when_it_changes(tmp_path, stub_extraction, monkeypatch):
    monkeypatch.setattr(course_sync.canvas, "get_course_structure", lambda course_id: [])
    monkeypatch.setattr(course_sync.canvas, "list_pages", lambda course_id: [])
    monkeypatch.setattr(course_sync.canvas, "get_syllabus", lambda course_id: "<p>Midterm is Oct 10.</p>")

    first = run(1, tmp_path)
    second = run(1, tmp_path)
    baseline = len(stub_extraction)
    monkeypatch.setattr(course_sync.canvas, "get_syllabus", lambda course_id: "<p>Midterm moved to Oct 17.</p>")
    third = run(1, tmp_path)

    assert first[-1]["new"] == 1 and {"item": "Syllabus", "status": "done"} in first
    assert second == [{"done": True, "new": 0, "changed": 0, "removed": 0, "failed": 0}]
    assert third[-1] == {"done": True, "new": 0, "changed": 1, "removed": 0, "failed": 0}
    assert [c for c in stub_extraction[baseline:] if c[0] == "delete"] == [("delete", "course_1", "syllabus:1")]
    assert _manifest_ids(tmp_path) == {"syllabus:1"}


def test_empty_or_unavailable_syllabus_is_skipped_and_never_deletes(tmp_path, stub_extraction, monkeypatch):
    monkeypatch.setattr(course_sync.canvas, "get_course_structure", lambda course_id: [])
    monkeypatch.setattr(course_sync.canvas, "list_pages", lambda course_id: [])
    monkeypatch.setattr(course_sync.canvas, "get_syllabus", lambda course_id: "<p>Office hours: Tue.</p>")
    run(1, tmp_path)

    for unavailable in (None, "", "<p> </p>"):
        monkeypatch.setattr(course_sync.canvas, "get_syllabus", lambda course_id, v=unavailable: v)
        monkeypatch.setattr(course_sync.ingestion, "extract_html_page", lambda html: (html or "").replace("<p>", "").replace("</p>", ""))
        events = run(1, tmp_path)
        assert events == [{"done": True, "new": 0, "changed": 0, "removed": 0, "failed": 0}]
    assert _manifest_ids(tmp_path) == {"syllabus:1"}
