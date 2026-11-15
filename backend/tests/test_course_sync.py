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


def _manifest_ids(sm_home, course_id=1):
    """Reads the real manifest.db the sync just wrote — deletion guards are
    about what survives on disk, not only about the emitted counts."""
    conn = course_sync.sync.open_manifest(sm_home / "courses" / str(course_id) / "manifest.db")
    try:
        return {row[0] for row in conn.execute("SELECT canvas_item_id FROM manifest").fetchall()}
    finally:
        conn.close()


@pytest.fixture(autouse=True)
def no_front_page_syllabus_or_assignments(monkeypatch):
    """Every test here stubs canvas per function; these default to "course
    has none" so no test can reach real Canvas through them (before this,
    unstubbed calls quietly hit the live API with the dev's own token).
    Tests about these sources override them."""
    monkeypatch.setattr(course_sync.canvas, "get_front_page", lambda course_id: None)
    monkeypatch.setattr(course_sync.canvas, "get_syllabus", lambda course_id: None)
    monkeypatch.setattr(course_sync.canvas, "list_assignments", lambda course_id: [])
    monkeypatch.setattr(course_sync.canvas, "list_course_files", lambda course_id: [])
    monkeypatch.setattr(course_sync.canvas, "list_announcements", lambda course_id: [])
    monkeypatch.setattr(course_sync.canvas, "list_discussions", lambda course_id: [])


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
    monkeypatch.setattr(course_sync.canvas, "download", lambda url: b"raw bytes")
    monkeypatch.setattr(
        course_sync.ingestion,
        "extract_pdf",
        lambda path, max_pages=None: [{"page": 1, "text": "syllabus content", "char_count": 17, "has_image": False, "needs_fallback": False}],
    )
    monkeypatch.setattr(course_sync.ingestion, "pdf_page_count", lambda path: 1)
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


def run(course_id, sm_home):
    return list(course_sync.sync_course(course_id, sm_home))


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
    monkeypatch.setattr(course_sync.canvas, "download", lambda url: b"raw bytes")
    monkeypatch.setattr(course_sync.ingestion, "pdf_page_count", lambda path: 1)
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


def _one_file(monkeypatch, name):
    monkeypatch.setattr(course_sync.canvas, "get_course_structure", lambda course_id: [{"items": [{"type": "File", "content_id": 333}]}])
    monkeypatch.setattr(
        course_sync.canvas,
        "get_file",
        lambda file_id: {"id": 333, "display_name": name, "updated_at": "2026-01-01", "url": "https://canvas.example/files/333"},
    )
    monkeypatch.setattr(course_sync.canvas, "list_pages", lambda course_id: [])


def test_unsupported_file_extension_is_skipped_not_synced(tmp_path, stub_extraction, monkeypatch, capsys):
    _one_file(monkeypatch, "lecture.mp4")

    events = run(1, tmp_path)

    assert events == [{"done": True, "new": 0, "changed": 0, "removed": 0, "failed": 0}]
    assert "lecture.mp4" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("name", "extractor"),
    [("Fintech App.docx", "extract_docx"), ("Papers.xlsx", "extract_xlsx"), ("notes.md", "extract_text_file"), ("data.csv", "extract_text_file")],
)
def test_word_excel_and_text_files_are_indexed_as_sections(tmp_path, stub_extraction, monkeypatch, name, extractor):
    _one_file(monkeypatch, name)
    monkeypatch.setattr(course_sync.ingestion, extractor, lambda path: [{"heading": "Requirements", "text": "Track spending."}])
    added = []
    monkeypatch.setattr(course_sync.indexing, "add_nodes", lambda nodes, db_path, table_name: added.extend(nodes))

    events = run(1, tmp_path)

    assert events[-1] == {"done": True, "new": 1, "changed": 0, "removed": 0, "failed": 0}
    [node] = added
    assert node.text == f"{name} › Requirements\nTrack spending."
    assert (node.metadata["source"], node.metadata["item_type"]) == (name, "file")
    assert node.ref_doc_id == "file:333"


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


# --- Assignment descriptions -------------------------------------------------


def _assignment(aid, name, description, updated_at="2026-01-01"):
    return {"id": aid, "name": name, "description": description, "updated_at": updated_at}


@pytest.fixture
def assignments_only(monkeypatch):
    monkeypatch.setattr(course_sync.canvas, "get_course_structure", lambda course_id: [])
    monkeypatch.setattr(course_sync.canvas, "list_pages", lambda course_id: [])
    monkeypatch.setattr(course_sync.ingestion, "extract_html_page", lambda html: (html or "").replace("<p>", "").replace("</p>", ""))

    def set_assignments(*items):
        monkeypatch.setattr(course_sync.canvas, "list_assignments", lambda course_id: [dict(a) for a in items])

    return set_assignments


def test_assignment_descriptions_are_indexed_and_empty_ones_skipped(tmp_path, stub_extraction, assignments_only):
    assignments_only(
        _assignment(1, "Task 1: Personas", "<p>Write two personas.</p>"),
        _assignment(2, "Task 2: Interviews", "<p>Interview three users.</p>"),
        _assignment(3, "Quiz 1", None),
        _assignment(4, "Participation", "<p> </p>"),
    )

    events = run(1, tmp_path)

    assert events[-1] == {"done": True, "new": 2, "changed": 0, "removed": 0, "failed": 0}
    assert {e["item"] for e in events if e.get("status") == "done"} == {"Task 1: Personas", "Task 2: Interviews"}
    assert _manifest_ids(tmp_path) == {"assignment:1", "assignment:2"}


def test_an_edited_assignment_is_resynced_and_a_cleared_one_removed(tmp_path, stub_extraction, assignments_only):
    assignments_only(_assignment(1, "Task 1", "<p>v1</p>"), _assignment(2, "Task 2", "<p>keep</p>"))
    run(1, tmp_path)
    baseline = len(stub_extraction)

    assignments_only(_assignment(1, "Task 1", "<p>v2</p>", "2026-02-01"), _assignment(2, "Task 2", None))
    events = run(1, tmp_path)

    assert events[-1] == {"done": True, "new": 0, "changed": 1, "removed": 1, "failed": 0}
    deleted = [c[2] for c in stub_extraction[baseline:] if c[0] == "delete"]
    assert sorted(deleted) == ["assignment:1", "assignment:2"]  # delete-before-add for 1, removal for 2
    assert _manifest_ids(tmp_path) == {"assignment:1"}


def test_an_empty_assignment_listing_deletes_nothing(tmp_path, stub_extraction, assignments_only):
    assignments_only(_assignment(1, "Task 1", "<p>text</p>"))
    run(1, tmp_path)

    assignments_only()  # a 403 degrades to [] — indistinguishable from "all removed"
    events = run(1, tmp_path)

    assert events == [{"done": True, "new": 0, "changed": 0, "removed": 0, "failed": 0}]
    assert _manifest_ids(tmp_path) == {"assignment:1"}


# --- Due dates and points ----------------------------------------------------


def test_schedule_line_reads_the_due_date_and_points_in_the_given_timezone():
    from datetime import timedelta, timezone

    eastern = timezone(timedelta(hours=-4), "EDT")
    line = course_sync.schedule_line({"due_at": "2026-09-15T14:00:00Z", "points_possible": 100.0}, eastern)

    assert line == "Due Tue, Sep 15, 2026 at 10:00 AM EDT. Worth 100 points."


def test_schedule_line_handles_missing_and_bad_values():
    assert course_sync.schedule_line({}) == ""
    assert course_sync.schedule_line({"due_at": None, "points_possible": 0}) == ""
    assert course_sync.schedule_line({"due_at": "not a date", "points_possible": 2.5}) == "Worth 2.5 points."


def test_an_assignment_with_a_due_date_but_no_description_is_indexed(tmp_path, stub_extraction, assignments_only):
    dated = {**_assignment(1, "Fall Break", None), "due_at": "2026-10-13T14:00:00Z"}
    assignments_only(dated, _assignment(2, "Quiz 1", None))

    events = run(1, tmp_path)

    assert events[-1] == {"done": True, "new": 1, "changed": 0, "removed": 0, "failed": 0}
    assert _manifest_ids(tmp_path) == {"assignment:1"}


def _outline_titles(sm_home, course_id=1):
    conn = course_sync.sync.open_manifest(sm_home / "courses" / str(course_id) / "manifest.db")
    try:
        return [row["title"] for row in course_sync.course_items.load_outline(conn)]
    finally:
        conn.close()


def test_sync_saves_the_module_outline_for_listing_questions(tmp_path, stub_canvas, stub_extraction, monkeypatch):
    structure = [
        {"name": "Week 1", "items": [{"type": "SubHeader", "title": "Readings"}, {"type": "File", "title": "Ch 1", "content_id": 111}]},
        {"name": "Week 2", "items": [{"type": "ExternalUrl", "title": "Video", "external_url": "https://v.example"}]},
    ]
    monkeypatch.setattr(course_sync.canvas, "get_course_structure", lambda course_id: structure)
    run(1, tmp_path)
    assert _outline_titles(tmp_path) == ["Ch 1", "Video"]


def test_an_empty_module_listing_keeps_the_saved_outline(tmp_path, stub_canvas, stub_extraction, monkeypatch):
    """Same guard as the deletions: a modules tab that comes back empty
    (hidden, or a Canvas hiccup) is not taken as "the course has no modules"."""
    titled = [{"name": "Week 1", "items": [{"type": "File", "title": "Ch 1", "content_id": 111}]}]
    monkeypatch.setattr(course_sync.canvas, "get_course_structure", lambda course_id: titled)
    run(1, tmp_path)
    monkeypatch.setattr(course_sync.canvas, "get_course_structure", lambda course_id: [])
    run(1, tmp_path)
    assert _outline_titles(tmp_path) == ["Ch 1"]



# --- Everything in the course menu, not only Modules -------------------------
# 18-658 lists no files in its Modules: all 46 of its readings are links in
# its pages and syllabus. 56350's Files tab has 24 files no module lists.

READING = {"id": 333, "display_name": "Koskela Ch1.pdf", "updated_at": "2026-01-01", "url": "https://canvas.example/files/333"}
SLIDES = {"id": 444, "display_name": "Lecture 2.pptx", "updated_at": "2026-01-01", "url": "https://canvas.example/files/444"}


def _link(file_id, course_id=1):
    return f'<p><a href="https://canvas.example/courses/{course_id}/files/{file_id}?wrap=1">reading</a></p>'


@pytest.fixture
def files_by_id(monkeypatch):
    """get_file over a small table; records which ids were looked up."""
    table = {333: READING, 444: SLIDES}
    asked = []

    def get_file(file_id):
        asked.append(int(file_id))
        meta = table.get(int(file_id))
        return dict(meta) if meta else None

    monkeypatch.setattr(course_sync.canvas, "get_file", get_file)
    monkeypatch.setattr(course_sync.canvas, "list_pages", lambda course_id: [])
    return asked


def _module_page_with_body(monkeypatch, body, url="task-1-resources", title="Task 1 Resources"):
    monkeypatch.setattr(
        course_sync.canvas,
        "get_course_structure",
        lambda course_id: [{"name": "Week 1", "items": [{"type": "Page", "title": title, "page_url": url}]}],
    )
    monkeypatch.setattr(
        course_sync.canvas, "get_page", lambda course_id, u: {"url": u, "title": title, "body": body, "updated_at": "1"}
    )


def test_a_file_linked_from_a_module_page_is_indexed(tmp_path, stub_extraction, files_by_id, monkeypatch):
    _module_page_with_body(monkeypatch, _link(333) + _link(333))
    run(1, tmp_path)
    assert "file:333" in _manifest_ids(tmp_path)
    assert files_by_id == [333]  # linked twice, looked up once


@pytest.mark.parametrize("where", ["syllabus", "front_page", "assignment", "announcement", "discussion"])
def test_files_linked_from_any_course_menu_text_are_indexed(tmp_path, stub_extraction, files_by_id, monkeypatch, where):
    monkeypatch.setattr(course_sync.canvas, "get_course_structure", lambda course_id: [])
    html = _link(333)
    if where == "syllabus":
        monkeypatch.setattr(course_sync.canvas, "get_syllabus", lambda course_id: html)
    elif where == "front_page":
        monkeypatch.setattr(
            course_sync.canvas, "get_front_page", lambda course_id: {"url": "home", "title": "Home", "body": html, "updated_at": "1"}
        )
    elif where == "assignment":
        monkeypatch.setattr(
            course_sync.canvas, "list_assignments", lambda course_id: [{"id": 9, "name": "A1", "description": html, "updated_at": "1"}]
        )
    else:
        topic = [{"id": 9, "title": "Read this", "message": html}]
        monkeypatch.setattr(course_sync.canvas, f"list_{where}s", lambda course_id: topic)
    run(1, tmp_path)
    assert "file:333" in _manifest_ids(tmp_path)


def test_a_link_to_another_courses_file_is_not_followed(tmp_path, stub_extraction, files_by_id, monkeypatch):
    _module_page_with_body(monkeypatch, _link(333, course_id=999) + '<a href="/files/444/download">slides</a>')
    run(1, tmp_path)
    assert files_by_id == [444]
    assert "file:333" not in _manifest_ids(tmp_path)


def test_pages_listed_without_a_body_are_read_for_their_links(tmp_path, stub_extraction, files_by_id, monkeypatch):
    monkeypatch.setattr(course_sync.canvas, "get_course_structure", lambda course_id: [])
    monkeypatch.setattr(course_sync.canvas, "list_pages", lambda course_id: [{"url": "intro", "title": "Intro", "updated_at": "1"}])
    monkeypatch.setattr(course_sync.canvas, "get_page", lambda course_id, u: {"url": u, "title": "Intro", "body": _link(444)})
    run(1, tmp_path)
    run(1, tmp_path)  # unchanged page: its links are still read, so the file isn't taken as deleted
    assert {"page:intro", "file:444"} <= _manifest_ids(tmp_path)


def test_files_tab_files_are_indexed_without_a_lookup_each(tmp_path, stub_extraction, files_by_id, monkeypatch):
    monkeypatch.setattr(course_sync.canvas, "get_course_structure", lambda course_id: [])
    monkeypatch.setattr(course_sync.canvas, "list_course_files", lambda course_id: [dict(READING), dict(SLIDES)])
    run(1, tmp_path)
    assert {"file:333", "file:444"} <= _manifest_ids(tmp_path)
    assert files_by_id == []


def test_a_file_in_modules_the_files_tab_and_a_link_is_indexed_once(tmp_path, stub_extraction, files_by_id, monkeypatch):
    monkeypatch.setattr(
        course_sync.canvas,
        "get_course_structure",
        lambda course_id: [{"name": "W1", "items": [{"type": "File", "title": "Koskela", "content_id": 333}]}],
    )
    monkeypatch.setattr(course_sync.canvas, "list_course_files", lambda course_id: [dict(READING)])
    monkeypatch.setattr(course_sync.canvas, "get_syllabus", lambda course_id: _link(333))
    events = run(1, tmp_path)
    assert [e["item"] for e in events if e.get("item") == "Koskela Ch1.pdf"] == ["Koskela Ch1.pdf"]
    assert files_by_id == []  # the Files tab already gave its details


def test_a_linked_file_that_cant_be_opened_is_not_deleted(tmp_path, stub_extraction, files_by_id, monkeypatch):
    _module_page_with_body(monkeypatch, _link(333))
    run(1, tmp_path)
    monkeypatch.setattr(course_sync.canvas, "get_file", lambda file_id: None)
    run(1, tmp_path)
    assert "file:333" in _manifest_ids(tmp_path)


def test_a_file_no_longer_linked_anywhere_is_removed(tmp_path, stub_extraction, files_by_id, monkeypatch):
    _module_page_with_body(monkeypatch, _link(333) + _link(444))
    run(1, tmp_path)
    _module_page_with_body(monkeypatch, _link(444) + "<p>edited</p>")
    run(1, tmp_path)
    ids = _manifest_ids(tmp_path)
    assert "file:444" in ids and "file:333" not in ids


def test_announcements_are_indexed_with_their_posted_date(tmp_path, stub_extraction, monkeypatch):
    monkeypatch.setattr(course_sync.canvas, "get_course_structure", lambda course_id: [])
    monkeypatch.setattr(course_sync.canvas, "list_pages", lambda course_id: [])
    added = []
    monkeypatch.setattr(course_sync.indexing, "add_nodes", lambda nodes, db_path, table_name: added.extend(nodes))
    monkeypatch.setattr(
        course_sync.canvas,
        "list_announcements",
        lambda course_id: [{"id": 7, "title": "Class This Tuesday", "message": "<p>We meet in room 101.</p>", "posted_at": "2026-10-26T07:49:06Z"}],
    )
    events = run(1, tmp_path)
    assert events[-1]["new"] == 1
    assert "announcement:7" in _manifest_ids(tmp_path)
    text = " ".join(n.get_content() for n in added)
    assert "room 101" in text and "Oct 26, 2026" in text
    assert {n.metadata["item_type"] for n in added} == {"announcement"}
    assert added[0].metadata["source"] == "Class This Tuesday"


def test_an_edited_announcement_is_resynced_and_a_removed_one_deleted(tmp_path, stub_extraction, monkeypatch):
    monkeypatch.setattr(course_sync.canvas, "get_course_structure", lambda course_id: [])
    monkeypatch.setattr(course_sync.canvas, "list_pages", lambda course_id: [])
    one = {"id": 7, "title": "Room", "message": "<p>Room 101</p>"}
    two = {"id": 8, "title": "Speaker", "message": "<p>Guest on Tuesday</p>"}
    monkeypatch.setattr(course_sync.canvas, "list_announcements", lambda course_id: [one, two])
    run(1, tmp_path)
    assert run(1, tmp_path)[-1] == {"done": True, "new": 0, "changed": 0, "removed": 0, "failed": 0}
    edited = {**one, "message": "<p>Room 202</p>"}
    monkeypatch.setattr(course_sync.canvas, "list_announcements", lambda course_id: [edited])
    summary = run(1, tmp_path)[-1]
    assert (summary["changed"], summary["removed"]) == (1, 1)
    assert "announcement:8" not in _manifest_ids(tmp_path)


def test_an_empty_announcement_listing_deletes_nothing(tmp_path, stub_extraction, monkeypatch):
    monkeypatch.setattr(course_sync.canvas, "get_course_structure", lambda course_id: [])
    monkeypatch.setattr(course_sync.canvas, "list_pages", lambda course_id: [])
    monkeypatch.setattr(course_sync.canvas, "list_announcements", lambda course_id: [{"id": 7, "title": "Room", "message": "<p>Room 101</p>"}])
    run(1, tmp_path)
    monkeypatch.setattr(course_sync.canvas, "list_announcements", lambda course_id: [])
    run(1, tmp_path)
    assert "announcement:7" in _manifest_ids(tmp_path)


def test_discussions_are_indexed_and_empty_ones_skipped(tmp_path, stub_extraction, monkeypatch):
    monkeypatch.setattr(course_sync.canvas, "get_course_structure", lambda course_id: [])
    monkeypatch.setattr(course_sync.canvas, "list_pages", lambda course_id: [])
    monkeypatch.setattr(
        course_sync.canvas,
        "list_discussions",
        lambda course_id: [{"id": 5, "title": "Updates", "message": "<p>Post weekly updates</p>"}, {"id": 6, "title": "Empty", "message": ""}],
    )
    run(1, tmp_path)
    ids = _manifest_ids(tmp_path)
    assert "discussion:5" in ids and "discussion:6" not in ids


def test_discussion_attachments_are_indexed_as_files(tmp_path, stub_extraction, monkeypatch):
    monkeypatch.setattr(course_sync.canvas, "get_course_structure", lambda course_id: [])
    monkeypatch.setattr(course_sync.canvas, "list_pages", lambda course_id: [])
    monkeypatch.setattr(
        course_sync.canvas,
        "list_announcements",
        lambda course_id: [{"id": 7, "title": "Slides", "message": "<p>Attached.</p>", "attachments": [dict(SLIDES)]}],
    )
    run(1, tmp_path)
    assert {"announcement:7", "file:444"} <= _manifest_ids(tmp_path)


def test_outline_lists_linked_files_under_their_page_and_the_rest_in_their_own_groups(tmp_path, stub_extraction, files_by_id, monkeypatch):
    _module_page_with_body(monkeypatch, _link(333))
    monkeypatch.setattr(course_sync.canvas, "list_course_files", lambda course_id: [dict(SLIDES)])
    monkeypatch.setattr(course_sync.canvas, "list_announcements", lambda course_id: [{"id": 7, "title": "Room", "message": "<p>Room 101</p>"}])
    monkeypatch.setattr(course_sync.canvas, "list_discussions", lambda course_id: [{"id": 5, "title": "Updates", "message": "<p>x</p>"}])
    run(1, tmp_path)
    conn = course_sync.sync.open_manifest(tmp_path / "courses" / "1" / "manifest.db")
    rows = [(r["module"], r["section"], r["title"], r["item_type"]) for r in course_sync.course_items.load_outline(conn)]
    conn.close()
    assert rows == [
        ("Week 1", "", "Task 1 Resources", "page"),
        ("Week 1", "Linked from Task 1 Resources", "Koskela Ch1.pdf", "file"),
        ("Other course files", "", "Lecture 2.pptx", "file"),
        ("Announcements", "", "Room", "announcement"),
        ("Discussions", "", "Updates", "discussion"),
    ]



# --- Large files wait for the student -----------------------------------------
# A PDF over 150 pages gets its first 150 indexed as a labeled preview; any
# other file whose text is over 450,000 characters gets a preview of that
# length; a file over 50 MB isn't downloaded. The student can turn the whole
# file on (large_files.set_want_full), and the next sync indexes all of it.

BOOK = {"id": 555, "display_name": "About Face.pdf", "updated_at": "2026-01-01", "url": "https://canvas.example/files/555", "size": 33_000_000}
HUGE = {"id": 666, "display_name": "Lecture videos.pdf", "updated_at": "2026-01-01", "url": "https://canvas.example/files/666", "size": 60_000_000}
NOTES = {"id": 777, "display_name": "Notes.docx", "updated_at": "2026-01-01", "url": "https://canvas.example/files/777", "size": 200_000}


@pytest.fixture
def book_course(tmp_path, stub_extraction, monkeypatch):
    """A course whose Files tab has the book, the huge file and the notes;
    records downloads, extract_pdf's max_pages and the nodes added."""
    seen = {"downloads": [], "max_pages": [], "sources": []}
    monkeypatch.setattr(course_sync.canvas, "get_course_structure", lambda course_id: [])
    monkeypatch.setattr(course_sync.canvas, "list_pages", lambda course_id: [])
    monkeypatch.setattr(course_sync.canvas, "list_course_files", lambda course_id: [dict(BOOK), dict(HUGE), dict(NOTES)])
    monkeypatch.setattr(course_sync.canvas, "download", lambda url: seen["downloads"].append(url) or b"raw bytes")
    monkeypatch.setattr(course_sync.ingestion, "pdf_page_count", lambda path: 722)

    def extract_pdf(path, max_pages=None):
        seen["max_pages"].append(max_pages)
        return [{"page": i, "text": f"page {i} text", "char_count": 11, "has_image": False, "needs_fallback": False} for i in range(1, (max_pages or 722) + 1)]

    monkeypatch.setattr(course_sync.ingestion, "extract_pdf", extract_pdf)
    monkeypatch.setattr(
        course_sync.ingestion, "extract_docx", lambda path: [{"heading": f"Part {i}", "text": "x" * 50} for i in range(10)]
    )
    monkeypatch.setattr(
        course_sync.indexing, "add_nodes", lambda nodes, db_path, table_name: seen["sources"].extend({n.metadata["source"] for n in nodes})
    )
    return seen


def _large(sm_home, course_id=1):
    conn = course_sync.sync.open_manifest(sm_home / "courses" / str(course_id) / "manifest.db")
    try:
        return {r["file_id"]: r for r in course_sync.large_files.rows(conn)}
    finally:
        conn.close()


def _want_full(sm_home, file_id, full=True, course_id=1):
    conn = course_sync.sync.open_manifest(sm_home / "courses" / str(course_id) / "manifest.db")
    try:
        assert course_sync.large_files.set_want_full(conn, file_id, full)
    finally:
        conn.close()


def test_a_pdf_over_150_pages_is_indexed_as_a_labeled_preview(tmp_path, book_course):
    run(1, tmp_path)
    assert book_course["max_pages"] == [150]
    assert "About Face.pdf (first 150 of 722 pages)" in book_course["sources"]
    book = _large(tmp_path)["555"]
    assert (book["pages"], book["state"], book["want_full"]) == (722, "preview", False)


def test_a_file_over_50_mb_is_not_downloaded(tmp_path, book_course):
    run(1, tmp_path)
    assert HUGE["url"] not in book_course["downloads"]
    assert "file:666" in _manifest_ids(tmp_path)
    assert _large(tmp_path)["666"]["state"] == "none"


def test_a_long_word_file_is_cut_to_its_text_limit(tmp_path, book_course, monkeypatch):
    monkeypatch.setattr(course_sync.large_files, "MAX_TEXT_CHARS", 200)
    run(1, tmp_path)
    assert "Notes.docx (first part)" in book_course["sources"]
    assert _large(tmp_path)["777"]["state"] == "preview"


def test_previews_are_left_alone_on_the_next_sync(tmp_path, book_course):
    run(1, tmp_path)
    book_course["downloads"].clear()
    summary = run(1, tmp_path)[-1]
    assert (summary["new"], summary["changed"]) == (0, 0)
    assert book_course["downloads"] == []


def test_turning_a_file_on_indexes_all_of_it_and_off_goes_back_to_the_preview(tmp_path, book_course):
    run(1, tmp_path)
    _want_full(tmp_path, "555")
    _want_full(tmp_path, "666")
    book_course["max_pages"].clear()
    summary = run(1, tmp_path)[-1]
    assert summary["changed"] == 2
    assert book_course["max_pages"] == [None, None]  # the book, and the huge file now downloaded
    assert HUGE["url"] in book_course["downloads"]
    assert "About Face.pdf" in book_course["sources"]
    assert _large(tmp_path)["555"]["state"] == "full"

    _want_full(tmp_path, "555", full=False)
    book_course["max_pages"].clear()
    assert run(1, tmp_path)[-1]["changed"] == 1
    assert book_course["max_pages"] == [150]
    assert _large(tmp_path)["555"]["state"] == "preview"


def test_the_outline_says_which_files_are_previews_or_not_synced(tmp_path, book_course):
    run(1, tmp_path)
    conn = course_sync.sync.open_manifest(tmp_path / "courses" / "1" / "manifest.db")
    titles = [r["title"] for r in course_sync.course_items.load_outline(conn)]
    conn.close()
    assert "About Face.pdf (first 150 of 722 pages synced)" in titles
    assert "Lecture videos.pdf (not synced: 60 MB)" in titles
    assert "Notes.docx" in titles


def test_a_large_file_removed_from_canvas_is_forgotten(tmp_path, book_course, monkeypatch):
    run(1, tmp_path)
    monkeypatch.setattr(course_sync.canvas, "list_course_files", lambda course_id: [dict(NOTES)])
    run(1, tmp_path)
    assert set(_large(tmp_path)) == set()
