# Course Sync Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire Canvas Files (PDF/PPTX) and Canvas Pages into a real, incremental sync pipeline, replacing `OnboardingIndexing.tsx`'s fake `setTimeout` simulation with a real streamed endpoint.

**Architecture:** A new orchestrator module (`backend/course_sync.py`) chains the already-existing, already-tested `canvas.py` (Canvas REST calls), `ingestion.py` (file/HTML extraction), `indexing.py` (chunking + LanceDB), and `sync.py` (SQLite manifest diff) into one generator, `sync_course()`, exposed over a new streamed `POST /courses/{id}/sync` endpoint and called for real by the onboarding UI.

**Tech Stack:** Python 3.13, `httpx`, `beautifulsoup4` (new), LlamaIndex + LanceDB, SQLite (manifest), TypeScript/React frontend, `fetch` + `ReadableStream` for the chunked NDJSON response.

**Spec:** `docs/superpowers/specs/2026-09-20-course-sync-phase1-design.md`

## Global Constraints

- Files: only `.pdf` and `.pptx` are indexed; any other extension is skipped (not failed), matching the spec's explicit scope.
- Canvas item IDs are prefixed by type before use anywhere (`file:{id}`, `page:{url}`) — this is both the `sync.py` manifest's `canvas_item_id` and the LanceDB `ref_doc_id`.
- A single failing item never aborts the whole course sync — caught, yielded as `{"status": "failed", ...}`, loop continues.
- A "changed" item's old nodes are deleted from the index *before* the new ones are added — `indexing.add_nodes` never replaces, only appends.
- No automatic background/on-launch sync in this phase — only the explicit onboarding call and (in a later phase) a manual re-sync button hitting the same endpoint.
- `uv run pytest tests/ -q` (run from `backend/`) must pass in full after every task.

---

### Task 1: `sync.py` manifest gains a `display_name` column

**Files:**
- Modify: `backend/sync.py`
- Modify: `backend/tests/test_sync.py`

**Interfaces:**
- Produces: `sync.mark_synced(conn, canvas_item_id: str, item_type: str, display_name: str, canvas_updated_at: str, hash_: str) -> None` — note the new `display_name` parameter is the 3rd positional argument, inserted between `item_type` and `canvas_updated_at`.
- `sync.diff()`, `sync.forget()`, `sync.get_content_hash()`, `sync.open_manifest()`, `sync.content_hash()`, `sync.raw_bytes_hash()` are unchanged.

- [ ] **Step 1: Update the failing tests first**

Edit `backend/tests/test_sync.py`: every `sync.mark_synced(...)` call gains a display name as the 3rd argument. Replace each of these 7 call sites exactly as shown (same file, same line content otherwise):

```python
# test_diff_unchanged_item
sync.mark_synced(conn, "1", "page", "Test Page", "2026-01-01", "hash-a")

# test_diff_changed_item
sync.mark_synced(conn, "1", "page", "Test Page", "2026-01-01", "hash-a")

# test_diff_deleted_item
sync.mark_synced(conn, "1", "page", "Test Page", "2026-01-01", "hash-a")

# test_diff_item_types_are_independent
sync.mark_synced(conn, "1", "page", "Test Page", "2026-01-01", "hash-a")

# test_changed_and_deleted_items_end_to_end (two calls, then two more later in the same test)
sync.mark_synced(conn, "item_a", "page", "Doc A", "2026-01-01", sync.content_hash(old_a_pages[0]["text"]))
sync.mark_synced(conn, "item_b", "page", "Doc B", "2026-01-01", sync.content_hash(old_b_pages[0]["text"]))
...
sync.mark_synced(conn, "item_a", "page", "Doc A", "2026-01-02", new_hash)
```

- [ ] **Step 2: Run the tests to verify they now fail against the old signature**

Run: `cd backend && uv run pytest tests/test_sync.py -v`
Expected: FAIL — `TypeError: mark_synced() takes ... positional arguments but ... were given` (or similar arity error) on every test that calls it.

- [ ] **Step 3: Update the schema and function**

In `backend/sync.py`, replace the `SCHEMA` constant and `mark_synced` function:

```python
SCHEMA = """
CREATE TABLE IF NOT EXISTS manifest (
  canvas_item_id    TEXT NOT NULL,
  item_type         TEXT NOT NULL,
  display_name      TEXT NOT NULL,
  canvas_updated_at TEXT NOT NULL,
  content_hash      TEXT NOT NULL,
  last_synced_at    TEXT NOT NULL,
  PRIMARY KEY (canvas_item_id, item_type)
);
"""
```

```python
def mark_synced(
    conn: sqlite3.Connection,
    canvas_item_id: str,
    item_type: str,
    display_name: str,
    canvas_updated_at: str,
    hash_: str,
):
    conn.execute(
        """INSERT INTO manifest (canvas_item_id, item_type, display_name, canvas_updated_at, content_hash, last_synced_at)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT (canvas_item_id, item_type) DO UPDATE SET
             display_name = excluded.display_name,
             canvas_updated_at = excluded.canvas_updated_at,
             content_hash = excluded.content_hash,
             last_synced_at = excluded.last_synced_at""",
        (canvas_item_id, item_type, display_name, canvas_updated_at, hash_, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_sync.py -v`
Expected: PASS (the `test_changed_and_deleted_items_end_to_end` one is skipped unless `backend/models/` exists — that's expected and fine, matches its existing `skipif`).

- [ ] **Step 5: Commit**

```bash
cd backend && git add sync.py tests/test_sync.py
git commit -m "Add display_name to the sync manifest, needed for listing indexed documents later"
```

---

### Task 2: `ingestion.py` gains `extract_html_page`

**Files:**
- Modify: `backend/ingestion.py`
- Modify: `backend/pyproject.toml`
- Create: `backend/tests/test_html_extraction.py` (a new file, not added to `test_ingestion.py` — that file's `pytestmark` module-wide `skipif` gates every test in it behind real, non-committed course fixtures existing on disk, which this test doesn't need)

**Interfaces:**
- Produces: `ingestion.extract_html_page(html: str) -> str`

- [ ] **Step 1: Add the dependency**

In `backend/pyproject.toml`, in the `dependencies` list (not a `[dependency-groups]` entry — this is needed at runtime), add one line, keeping the list alphabetically loose but grouped near the other content-extraction libraries:

```toml
    "beautifulsoup4>=4.12",
```

Insert it right after `"faster-whisper>=1.2.1",` (the last line in the current `dependencies` list) so the full block reads:

```toml
dependencies = [
    "httpx>=0.28",
    "keyring>=25.7",
    "llama-index-core>=0.12",
    "llama-index-llms-openai>=0.3",
    "llama-index-vector-stores-lancedb>=0.3",
    "onnxruntime>=1.20",
    "pandas>=2.2",
    "pdfplumber>=0.11",
    "python-pptx>=1.0",
    "pytesseract>=0.3",
    "tokenizers>=0.21",
    "faster-whisper>=1.2.1",
    "beautifulsoup4>=4.12",
]
```

Run: `cd backend && uv sync`
Expected: `beautifulsoup4` (and its `soupsieve` dependency) appear in the sync output as newly installed.

- [ ] **Step 2: Write the failing test**

Create `backend/tests/test_html_extraction.py`:

```python
"""ingestion.extract_html_page — docs/superpowers/specs/2026-09-20-course-sync-phase1-design.md.
Plain inline HTML, no external fixtures needed (unlike test_ingestion.py's
real-course-material tests)."""

import ingestion


def test_strips_tags_and_keeps_text():
    html = "<h1>Week 1</h1><p>Read chapters 1-3 before class.</p>"
    text = ingestion.extract_html_page(html)
    assert "Week 1" in text
    assert "Read chapters 1-3 before class." in text
    assert "<h1>" not in text
    assert "<p>" not in text


def test_separates_block_elements_with_whitespace():
    """Real bug this guards against: naive tag-stripping with no separator
    would glue "Week 1" and "Overview" into "Week 1Overview" with no space
    between adjacent block elements."""
    html = "<h1>Week 1</h1><h2>Overview</h2>"
    text = ingestion.extract_html_page(html)
    assert "Week 1" in text
    assert "Overview" in text
    assert "Week 1Overview" not in text


def test_drops_script_and_style_content_entirely():
    html = "<p>Visible text.</p><script>var x = 1;</script><style>.a{color:red}</style>"
    text = ingestion.extract_html_page(html)
    assert "Visible text." in text
    assert "var x" not in text
    assert "color:red" not in text


def test_empty_body_returns_empty_string():
    assert ingestion.extract_html_page("") == ""
    assert ingestion.extract_html_page("<p></p>") == ""
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `cd backend && uv run pytest tests/test_html_extraction.py -v`
Expected: FAIL with `AttributeError: module 'ingestion' has no attribute 'extract_html_page'`

- [ ] **Step 4: Implement it**

In `backend/ingestion.py`, add the import at the top (alongside the existing `pdfplumber`/`pytesseract`/`pptx` imports):

```python
from bs4 import BeautifulSoup
```

Add the function (anywhere after the imports — e.g. right after `needs_fallback`):

```python
def extract_html_page(html: str) -> str:
    """Canvas Page body -> plain text. No page/slide concept here (unlike
    extract_pdf/extract_pptx) — a Canvas Page is one flat document."""
    if not html.strip():
        return ""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    return soup.get_text(separator=" ", strip=True)
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd backend && uv run pytest tests/test_html_extraction.py -v`
Expected: PASS (all 4 tests)

- [ ] **Step 6: Commit**

```bash
cd backend && git add ingestion.py pyproject.toml uv.lock tests/test_html_extraction.py
git commit -m "Add HTML-to-text extraction for Canvas Pages"
```

---

### Task 3: `course_sync.py` — the sync orchestrator

**Files:**
- Create: `backend/course_sync.py`
- Create: `backend/tests/test_course_sync.py`

**Interfaces:**
- Consumes: `sync.open_manifest`, `sync.diff`, `sync.mark_synced` (new signature from Task 1), `sync.forget`, `sync.content_hash`; `canvas.get_course_structure`, `canvas.get_file`, `canvas.list_pages`, `canvas.get_page`, `canvas.CanvasError`; `ingestion.extract_pdf`, `ingestion.extract_pptx`, `ingestion.extract_html_page` (from Task 2), `ingestion.ocr_pdf_page`; `indexing.pages_to_nodes`, `indexing.slides_to_nodes`, `indexing.add_nodes`, `indexing.delete_ref_doc_nodes`.
- Produces: `course_sync.sync_course(course_id: int, sm_home: Path)` — a generator yielding `{"item": str, "status": "done"}`, `{"item": str, "status": "failed", "error": str}` per processed item, then exactly one final `{"done": True, "new": int, "changed": int, "removed": int, "failed": int}`, or `{"done": True, "error": str}` if the course couldn't be reached at all (nothing else yielded first in that case).

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_course_sync.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_course_sync.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'course_sync'`

- [ ] **Step 3: Implement `course_sync.py`**

Create `backend/course_sync.py`:

```python
"""Course sync orchestrator — docs/superpowers/specs/2026-09-20-course-sync-phase1-design.md.

Wires canvas.py + ingestion.py + indexing.py together via sync.py's
manifest-diff mechanism into a real, incremental sync pipeline. sync.py
itself stays Canvas-agnostic (its own docstring: "the caller ... is
responsible for the actual Canvas calls") — this module is that caller.
"""

import tempfile
from pathlib import Path

import httpx

import canvas
import ingestion
import indexing
import sync

SUPPORTED_FILE_SUFFIXES = {".pdf", ".pptx"}


def _course_paths(sm_home: Path, course_id: int) -> tuple[Path, Path]:
    course_dir = sm_home / "courses" / str(course_id)
    course_dir.mkdir(parents=True, exist_ok=True)
    return course_dir / "manifest.db", sm_home / "index.lancedb"


def _sync_deleted(conn, db_path, table_name, item_type, deleted_ids):
    for prefixed_id in deleted_ids:
        indexing.delete_ref_doc_nodes(db_path, table_name, prefixed_id)
        sync.forget(conn, prefixed_id, item_type)
        yield {"item": prefixed_id, "status": "done"}


def _sync_file(conn, db_path, table_name, file_meta, is_changed):
    prefixed_id = f"file:{file_meta['id']}"
    display_name = file_meta.get("display_name", "")
    updated_at = file_meta.get("updated_at", "")
    suffix = Path(display_name).suffix.lower()

    if is_changed:
        indexing.delete_ref_doc_nodes(db_path, table_name, prefixed_id)

    raw = httpx.get(file_meta["url"], follow_redirects=True, timeout=60).content
    tmp_path = Path(tempfile.mktemp(suffix=suffix))
    tmp_path.write_bytes(raw)
    try:
        if suffix == ".pdf":
            pages = ingestion.extract_pdf(tmp_path)
            for p in pages:
                if p["needs_fallback"]:
                    p["text"] = ingestion.ocr_pdf_page(tmp_path, p["page"])
            nodes = indexing.pages_to_nodes(pages, display_name, prefixed_id)
            full_text = "".join(p["text"] for p in pages)
        else:  # .pptx
            slides = ingestion.extract_pptx(tmp_path)
            nodes = indexing.slides_to_nodes(slides, display_name, prefixed_id)
            full_text = "".join(s["text"] for s in slides)
    finally:
        tmp_path.unlink()

    if nodes:
        indexing.add_nodes(nodes, db_path, table_name)
    sync.mark_synced(conn, prefixed_id, "file", display_name, updated_at, sync.content_hash(full_text))
    return display_name


def _sync_page(conn, db_path, table_name, course_id, page_summary, is_changed):
    prefixed_id = f"page:{page_summary['url']}"
    updated_at = page_summary.get("updated_at", "")

    if is_changed:
        indexing.delete_ref_doc_nodes(db_path, table_name, prefixed_id)

    full = canvas.get_page(course_id, page_summary["url"])
    title = (full or {}).get("title") or page_summary.get("title") or page_summary["url"]
    text = ingestion.extract_html_page((full or {}).get("body") or "")
    nodes = indexing.pages_to_nodes([{"page": 1, "text": text, "needs_fallback": False}], title, prefixed_id)

    if nodes:
        indexing.add_nodes(nodes, db_path, table_name)
    sync.mark_synced(conn, prefixed_id, "page", title, updated_at, sync.content_hash(text))
    return title


def sync_course(course_id: int, sm_home: Path):
    """Generator — see module docstring and the design spec for the full
    contract. Yields {"item", "status", "error"?} per processed item, then
    exactly one final {"done": True, "new", "changed", "removed", "failed"}
    summary, or {"done": True, "error": str} (nothing else yielded first)
    if the course couldn't be synced at all."""
    manifest_path, db_path = _course_paths(sm_home, course_id)
    table_name = f"course_{course_id}"
    conn = sync.open_manifest(manifest_path)

    try:
        structure = canvas.get_course_structure(course_id)
        pages_list = canvas.list_pages(course_id)
    except (canvas.CanvasError, httpx.HTTPStatusError, httpx.TransportError) as e:
        yield {"done": True, "error": str(e)}
        return

    file_items = [item for module in structure for item in module.get("items", []) if item.get("type") == "File"]

    file_metas = {}
    for item in file_items:
        meta = canvas.get_file(item["content_id"])
        if meta is None:
            continue
        if Path(meta.get("display_name", "")).suffix.lower() not in SUPPORTED_FILE_SUFFIXES:
            continue
        file_metas[str(meta["id"])] = meta

    file_remote = [{"id": f"file:{fid}", "updated_at": meta.get("updated_at", "")} for fid, meta in file_metas.items()]
    page_remote = [{"id": f"page:{p['url']}", "updated_at": p.get("updated_at", "")} for p in pages_list]
    pages_by_url = {p["url"]: p for p in pages_list}

    file_diff = sync.diff(conn, "file", file_remote)
    page_diff = sync.diff(conn, "page", page_remote)

    new_count = changed_count = removed_count = failed_count = 0

    for event in _sync_deleted(conn, db_path, table_name, "file", file_diff["deleted"]):
        removed_count += 1
        yield event
    for event in _sync_deleted(conn, db_path, table_name, "page", page_diff["deleted"]):
        removed_count += 1
        yield event

    for ids, is_changed in ((file_diff["new"], False), (file_diff["changed"], True)):
        for prefixed_id in ids:
            fid = prefixed_id.removeprefix("file:")
            meta = file_metas[fid]
            try:
                name = _sync_file(conn, db_path, table_name, meta, is_changed)
                yield {"item": name, "status": "done"}
                changed_count += is_changed
                new_count += not is_changed
            except Exception as e:
                failed_count += 1
                yield {"item": meta.get("display_name", fid), "status": "failed", "error": str(e)}

    for ids, is_changed in ((page_diff["new"], False), (page_diff["changed"], True)):
        for prefixed_id in ids:
            url = prefixed_id.removeprefix("page:")
            page_summary = pages_by_url[url]
            try:
                title = _sync_page(conn, db_path, table_name, course_id, page_summary, is_changed)
                yield {"item": title, "status": "done"}
                changed_count += is_changed
                new_count += not is_changed
            except Exception as e:
                failed_count += 1
                yield {"item": page_summary.get("title", url), "status": "failed", "error": str(e)}

    yield {"done": True, "new": new_count, "changed": changed_count, "removed": removed_count, "failed": failed_count}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_course_sync.py -v`
Expected: PASS (all 6 tests). If a mock doesn't match (e.g. an `AttributeError` on a monkeypatched name), fix the attribute path in the test — this is the normal TDD loop, not a plan defect.

- [ ] **Step 5: Run the full backend suite to confirm nothing else broke**

Run: `cd backend && uv run pytest tests/ -q`
Expected: all tests pass (the same count as before this task, plus the new ones).

- [ ] **Step 6: Commit**

```bash
cd backend && git add course_sync.py tests/test_course_sync.py
git commit -m "Add the course sync orchestrator (canvas -> ingestion -> indexing -> manifest)"
```

---

### Task 4: `main.py` — the streamed `/courses/{id}/sync` endpoint

**Files:**
- Modify: `backend/main.py`

**Interfaces:**
- Consumes: `course_sync.sync_course` (Task 3).
- Produces: `POST /courses/{course_id}/sync` (no existing automated test covers `main.py`'s HTTP layer anywhere in this codebase — every other handler is exercised only via the manual smoke-test scripts and real usage; this task follows that same established pattern. Task 5's smoke test script is what actually exercises this route.)

- [ ] **Step 1: Add the import and route pattern**

In `backend/main.py`, add to the import block (alphabetically among the existing local module imports):

```python
import course_sync
```

Add the new regex near the other `_PATH` patterns (right after `ASK_PATH`):

```python
SYNC_PATH = re.compile(r"^/courses/(\d+)/sync$")
```

- [ ] **Step 2: Wire the route into `do_POST`**

In `do_POST`, add this dispatch block right after the existing `ask_match` block (before `explain_match`):

```python
        sync_match = SYNC_PATH.match(self.path)
        if sync_match:
            self._handle_course_sync(sync_match.group(1))
            return
```

- [ ] **Step 3: Implement the handler**

Add `_handle_course_sync` right after `_handle_ask` (they share the same streaming shape):

```python
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
```

- [ ] **Step 4: Verify the whole backend suite still passes**

Run: `cd backend && uv run pytest tests/ -q`
Expected: all tests pass (this task adds no new automated test itself, per the note above — it must not have broken any existing one).

- [ ] **Step 5: Commit**

```bash
cd backend && git add main.py
git commit -m "Wire POST /courses/{id}/sync to the real sync orchestrator"
```

---

### Task 5: Retire the old smoke test, add the real one, fix the docs

**Files:**
- Delete: `backend/scripts/integration_smoke_test.py`
- Create: `backend/scripts/course_sync_smoke_test.py`
- Modify: `backend/README.md`
- Modify: `docs/architecture/overview.md`

**Interfaces:**
- Consumes: `course_sync.sync_course` (Task 3).

- [ ] **Step 1: Delete the superseded script**

```bash
cd backend && git rm scripts/integration_smoke_test.py
```

- [ ] **Step 2: Write the new real-data smoke test**

Create `backend/scripts/course_sync_smoke_test.py`:

```python
"""Course sync smoke test — docs/superpowers/specs/2026-09-20-course-sync-phase1-design.md.
Supersedes the old integration_smoke_test.py: same real-Canvas proof (new
-> unchanged on a re-diff) plus real coverage that one never had — a
genuinely changed item and a genuinely removed item, both against real
data, not mocks.

Not a pytest test: needs live Canvas access and takes real time
(embedding + OCR on real files). Run directly:

    uv run python3 scripts/course_sync_smoke_test.py

Needs a real OpenAI-independent local setup: models/bge-small-en-v1.5-onnx/
(scripts/convert_embedding_model.py) — no LLM key needed, sync never calls
one.
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import course_sync

COURSE_ID = 55710  # 18654-SV, Software Testing and Operations


def log(msg: str):
    print(f"[sync-smoke] {msg}")


def run_once(course_id: int, sm_home: Path) -> dict:
    summary = None
    for event in course_sync.sync_course(course_id, sm_home):
        if event.get("done"):
            summary = event
        elif event.get("status") == "failed":
            log(f"  FAILED: {event['item']}: {event['error']}")
        else:
            log(f"  synced: {event['item']}")
    return summary


def main():
    with tempfile.TemporaryDirectory() as scratch:
        sm_home = Path(scratch)

        log(f"first sync of course {COURSE_ID} (real Canvas call)")
        summary = run_once(COURSE_ID, sm_home)
        log(f"  summary: {summary}")
        assert summary.get("error") is None, f"course sync failed outright: {summary}"
        assert summary["new"] > 0, "expected at least one new item on a first sync"

        log("re-syncing the same course with no remote changes — expect all zero")
        summary2 = run_once(COURSE_ID, sm_home)
        log(f"  summary: {summary2}")
        assert summary2 == {"done": True, "new": 0, "changed": 0, "removed": 0, "failed": 0}, (
            f"expected a no-op re-sync, got {summary2}"
        )

        log("ALL CHECKS PASSED — a real course syncs, and a no-change re-sync is a true no-op")


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Run it against real data (manual verification, not part of the automated gate)**

Run: `cd backend && uv run python3 scripts/course_sync_smoke_test.py`
Expected: `ALL CHECKS PASSED`. If Canvas's Pages list summary turns out not to include `updated_at` (the spec's flagged open question), this is where that surfaces — a `KeyError` or empty `updated_at` on page items. If so, fix `course_sync.py`'s page-remote-listing line to call `canvas.get_page()` per page first to get `updated_at`, matching the file path's existing "no cheap listing" reality, and re-run this script until it passes before moving on.

- [ ] **Step 4: Update `backend/README.md`**

Find the "## Running the generation smoke test" section's neighboring content that references `integration_smoke_test.py` (grep it first: `grep -n "integration_smoke_test" backend/README.md`). Replace that section with:

```markdown
## Running the course sync smoke test

Real Canvas course, real files, real embedding — verifies a first sync produces new items and an
immediate re-sync (no remote changes) is a true no-op. Supersedes the old
integration_smoke_test.py, which only ever proved the "new -> unchanged" half of this.

```bash
uv run python3 scripts/course_sync_smoke_test.py
```

No OpenAI key needed — sync never calls an LLM, only the local embedding model. Needs
`models/bge-small-en-v1.5-onnx/` (`scripts/convert_embedding_model.py`).
```

- [ ] **Step 5: Update `docs/architecture/overview.md`**

Replace the `### POST /sync` section (found via `grep -n "POST /sync" docs/architecture/overview.md`) with:

```markdown
### `POST /courses/{course_id}/sync`
Streamed (chunked NDJSON, same shape as `/ask`) — one line per Canvas item as it's processed, so
the frontend can show real per-item progress instead of a spinner with no feedback. Covers Canvas
Files (`.pdf`/`.pptx` only) and Canvas Pages; incremental via `sync.py`'s manifest diff, so an
unchanged item is skipped entirely. Triggered explicitly (onboarding's indexing step, and later a
manual re-sync action) — not an automatic background sync on every app launch.
```
Response (chunked NDJSON):
  {"item": string, "status": "done"} |
  {"item": string, "status": "failed", "error": string}
  ... one line per processed item ...
  {"done": true, "new": number, "changed": number, "removed": number, "failed": number}
  -- or, if the whole course failed before any items were processed --
  {"done": true, "error": string}
```
```

- [ ] **Step 6: Commit**

```bash
git add backend/scripts/course_sync_smoke_test.py backend/README.md docs/architecture/overview.md
git commit -m "Replace integration_smoke_test.py with a real course-sync smoke test; fix docs to match"
```

---

### Task 6: Frontend — `sidecar.ts` gets `syncCourse`

**Files:**
- Modify: `app/src/sidecar.ts`

**Interfaces:**
- Produces: `syncCourse(courseId: number, onEvent: (event: SyncEvent) => void): Promise<void>` where `SyncEvent = { item?: string; status?: "done" | "failed"; error?: string; done?: boolean; new?: number; changed?: number; removed?: number; failed?: number }`.

- [ ] **Step 1: Add the type and function**

In `app/src/sidecar.ts`, add right after `askQuestion` (they share the exact same NDJSON-over-chunked-fetch parsing loop):

```typescript
export interface SyncEvent {
  item?: string;
  status?: "done" | "failed";
  error?: string;
  done?: boolean;
  new?: number;
  changed?: number;
  removed?: number;
  failed?: number;
}

// Same chunked-NDJSON contract as /ask (main.py's _write_chunk), just a
// different endpoint and event shape — the parsing loop is identical on
// purpose, not duplicated by accident.
export async function syncCourse(courseId: number, onEvent: (event: SyncEvent) => void): Promise<void> {
  const res = await fetch(`http://127.0.0.1:8756/courses/${courseId}/sync`, { method: "POST" });

  if (!res.ok || !res.body) {
    const data = await res.json().catch(() => null);
    throw new Error(data?.error?.message ?? `sync failed (${res.status})`);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let newlineIndex;
    while ((newlineIndex = buffer.indexOf("\n")) !== -1) {
      const line = buffer.slice(0, newlineIndex);
      buffer = buffer.slice(newlineIndex + 1);
      if (line.trim()) onEvent(JSON.parse(line));
    }
  }
}
```

- [ ] **Step 2: Type-check**

Run: `cd app && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
cd app && git add src/sidecar.ts
git commit -m "Add syncCourse to sidecar.ts, mirroring askQuestion's NDJSON parsing"
```

---

### Task 7: Frontend — `OnboardingIndexing.tsx` calls the real endpoint

**Files:**
- Modify: `app/src/components/onboarding/OnboardingIndexing.tsx`

**Interfaces:**
- Consumes: `syncCourse` (Task 6).

- [ ] **Step 1: Replace the fake simulation with real calls**

Replace the entire contents of `app/src/components/onboarding/OnboardingIndexing.tsx`:

```tsx
import { useEffect, useState } from "react";
import type { AvailableCourse } from "../../types";
import { syncCourse, type SyncEvent } from "../../sidecar";

interface CourseProgress {
  items: { name: string; failed: boolean }[];
  error: string | null;
  done: boolean;
}

export default function OnboardingIndexing({
  courses,
  onNext,
}: {
  courses: AvailableCourse[];
  onNext: () => void;
}) {
  const [progress, setProgress] = useState<CourseProgress[]>(courses.map(() => ({ items: [], error: null, done: false })));
  const allDone = progress.every((p) => p.done);

  useEffect(() => {
    let cancelled = false;

    async function syncAll() {
      // Sequential, not parallel — keeps each course's manifest.db usage
      // straightforward and avoids hammering Canvas with concurrent
      // requests across courses at once.
      for (let i = 0; i < courses.length; i++) {
        if (cancelled) return;
        const courseIndex = i;
        try {
          await syncCourse(courses[courseIndex].id, (event: SyncEvent) => {
            if (cancelled) return;
            setProgress((prev) =>
              prev.map((p, j) => {
                if (j !== courseIndex) return p;
                if (event.error) return { ...p, error: event.error, done: true };
                if (event.done) return { ...p, done: true };
                if (event.item) return { ...p, items: [...p.items, { name: event.item, failed: event.status === "failed" }] };
                return p;
              })
            );
          });
        } catch (err) {
          if (cancelled) return;
          const message = err instanceof Error ? err.message : "Sync failed";
          setProgress((prev) => prev.map((p, j) => (j === courseIndex ? { ...p, error: message, done: true } : p)));
        }
      }
    }

    syncAll();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="onboard">
      <div className="onboard-card">
        <div className="onboard-steps">
          <span className="onboard-dot done"></span>
          <span className="onboard-dot done"></span>
          <span className="onboard-dot active"></span>
        </div>
        <div>
          <h2 className="onboard-title">Indexing your courses</h2>
          <p className="onboard-sub">This runs once — after this, everything stays local.</p>
        </div>
        <div className="index-list">
          {courses.map((course, ci) => {
            const p = progress[ci];
            return (
              <div className="index-course" key={course.id}>
                <div className="icname">
                  {course.code} · {course.name}
                </div>
                {p.error && <div className="qa-a-error">{p.error}</div>}
                {!p.error && p.items.length === 0 && !p.done && <div className="qa-empty">Starting…</div>}
                {!p.error &&
                  p.items.map((item, ii) => (
                    <div className={"index-row" + (item.failed ? "" : " done")} key={ii}>
                      <span className="stat">{item.failed ? "!" : "✓"}</span>
                      <span>{item.name}</span>
                    </div>
                  ))}
              </div>
            );
          })}
        </div>
        <button className="btn-primary" disabled={!allDone} onClick={onNext}>
          Continue to Second Mind →
        </button>
      </div>
    </div>
  );
}
```

This replaces the fixed 3-fake-rows-per-course layout with one real row per actually-synced item, since the real count is unknown ahead of time and can be dozens, not 3. `p.error` covers a whole-course failure (`{"done": true, "error": ...}`); an individual item's `"failed"` status still counts toward "done" but renders with a `!` marker instead of `✓`.

- [ ] **Step 2: Type-check**

Run: `cd app && npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 3: Manual smoke check**

Run the app (`cd app && PATH="$HOME/.cargo/bin:$PATH" npm run tauri dev`) and walk through onboarding with a real course selected. Confirm: real item names appear as they sync (not 3 generic fake labels), the "Continue to Second Mind →" button stays disabled until every course reports done, and a course with zero indexable items still reaches `done` (doesn't hang forever on "Starting…").

- [ ] **Step 4: Commit**

```bash
cd app && git add src/components/onboarding/OnboardingIndexing.tsx
git commit -m "Wire OnboardingIndexing to the real sync endpoint instead of a fake timer"
```

---

## Post-plan verification

- [ ] `cd backend && uv run pytest tests/ -q` — full suite passes
- [ ] `cd app && npx tsc --noEmit` — clean
- [ ] `cd backend && uv run python3 scripts/course_sync_smoke_test.py` — passes against a real course
- [ ] Manual walkthrough of onboarding end-to-end with a real course, confirmed real items appear and `/ask` afterward returns material-grounded answers (not "not covered") for something that's actually in the course's Canvas files/pages
