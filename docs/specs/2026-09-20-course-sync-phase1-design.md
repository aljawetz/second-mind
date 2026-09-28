# Course sync, Phase 1: real Canvas indexing — design

**Status:** implemented — see `docs/plans/2026-09-20-course-sync-phase1.md`
**Depends on:** nothing (all consumed modules already exist and are tested)
**Blocks:** Phase 2 (view indexed documents), Phase 3 (remove a document), Phase 4 (upload a document)

## 1. Problem

`main.py` has no endpoint that actually populates a course's index from Canvas.
`OnboardingIndexing.tsx` — the "Indexing your courses" onboarding screen — is a
pure `setTimeout` simulation with zero backend calls. The building blocks all
exist and are individually tested (`canvas.py`, `ingestion.py`, `indexing.py`,
`sync.py`'s manifest), but nothing wires them together. Today, the only way a
course's LanceDB table ever gets rows in it is via session-recording capture
(`sessions.py`), never via Canvas material. `/ask` against a course with no
recorded sessions yet always returns "not covered," regardless of how much
real material exists on Canvas for that course.

This phase closes that gap: a real, incremental sync pipeline for Canvas
Files (PDF/PPTX) and Canvas Pages, wired to the existing manifest-diff
mechanism in `sync.py`, exposed over one streamed HTTP endpoint, and called
for real by the onboarding flow.

## 2. Scope

**In scope:**
- Canvas module items of type `File` where the file extension is `.pdf` or
  `.pptx`
- Canvas Pages (`GET /courses/{id}/pages`, page bodies as HTML)
- Incremental re-sync: unchanged items are skipped (via `sync.diff()`),
  changed items are re-extracted and re-embedded, removed items are deleted
  from the index
- One new endpoint, streamed, so the frontend can show real per-item progress
- Wiring `OnboardingIndexing.tsx` to call it for real

**Explicitly out of scope for this phase** (do not implement):
- The course syllabus (`syllabus_body` on the course object) — HTML, but a
  different fetch path than Pages; a fast-follow, not this phase
- Any file type other than `.pdf`/`.pptx` (`.docx`, images, etc.) — skipped,
  not failed, with a log line
- A manual "re-sync" trigger button anywhere in the app UI — that's Phase 2's
  UI calling this same endpoint; this phase only wires the automatic
  onboarding call
- Any change to how session-recording indexing works (`sessions.py`) — that
  path is already real and untouched
- **Automatic background re-sync on every app launch.** `overview.md`
  already documents a `POST /sync` contract described as running "on app
  launch, asynchronously" for every selected course at once, non-streamed,
  written before any of this was built. This phase deliberately does not
  build that: it's a materially different feature (silent, periodic,
  all-courses-at-once) from what was actually asked for (a student-visible
  way to see/add/remove indexed material), and building it now would be
  scope creep beyond the sync-and-view-management arc this phase and the
  next three exist to deliver. `overview.md` gets corrected in this phase
  to document the real, narrower contract being built (§3.4 above) instead
  of the aspirational one — see 4.

## 3. New/changed components

### 3.1 `backend/sync.py` — schema change only

Add a `display_name` column to the `manifest` table, and a `display_name`
parameter to `mark_synced()`:

```sql
CREATE TABLE IF NOT EXISTS manifest (
  canvas_item_id    TEXT NOT NULL,
  item_type         TEXT NOT NULL,
  display_name      TEXT NOT NULL,
  canvas_updated_at TEXT NOT NULL,
  content_hash      TEXT NOT NULL,
  last_synced_at    TEXT NOT NULL,
  PRIMARY KEY (canvas_item_id, item_type)
);
```

```python
def mark_synced(conn, canvas_item_id: str, item_type: str, display_name: str,
                 canvas_updated_at: str, hash_: str):
```

Existing callers to update in the same commit: `tests/test_sync.py` (7 call
sites). `scripts/integration_smoke_test.py`'s `sync_file()` also calls
`mark_synced()` but is retired outright by this phase rather than patched —
see 3.3 and 4.

This is the only schema/interface change to an existing module. `diff()`,
`forget()`, `get_content_hash()`, `open_manifest()` are unchanged.

### 3.2 `backend/ingestion.py` — one new function

```python
def extract_html_page(html: str) -> str:
    """Canvas Page body -> plain text, via BeautifulSoup. No page/slide
    concept here — a Canvas Page is one flat document, unlike a paginated
    PDF or a slide deck."""
```

New dependency: `beautifulsoup4` (added to `[project.dependencies]` in
`pyproject.toml`, not a dependency group — needed at runtime, not just for
tests/build/conversion).

`extract_pdf`, `extract_pptx`, `ocr_pdf_page`, `needs_fallback` are unchanged.

### 3.3 `backend/course_sync.py` — new module (the orchestrator)

This is the only new module. It is deliberately kept separate from
`sync.py`, matching that module's existing design intent (its docstring:
"the caller — wherever real sync gets orchestrated — is responsible for the
actual Canvas calls"). `sync.py` stays Canvas-agnostic and fixture-testable;
`course_sync.py` is where the real Canvas/ingestion/indexing calls happen.

**Real prior art, not a clean-slate design**: `scripts/integration_smoke_test.py`
already implements almost exactly the Files half of this (`sync_file()`,
lines 43-90) and has been run against live Canvas data — its own log output
confirms "real Canvas updated_at timestamps round-trip correctly through the
manifest" on a real re-diff. `course_sync.py`'s file-handling logic should
be lifted from that script almost directly, with three real differences:
(1) it uses `indexing.add_nodes()` instead of calling `build_index()` on
every item in a loop (the existence-aware helper is the documented-correct
one for repeated inserts into a table that may already exist); (2) it
actually handles the `changed`/`deleted` buckets, which the smoke test
never exercises (it only ever proves `new` → `unchanged`, never a real
content change or removal); (3) it's a generator yielding progress instead
of a script printing log lines. `sync_file()`'s smoke test itself must be
updated for `mark_synced()`'s new `display_name` parameter regardless of
whether its logic gets literally reused (see 3.1).

```python
def sync_course(course_id: int, sm_home: Path):
    """Generator. Yields one dict per processed item:
      {"item": display_name, "status": "done" | "failed", "error"?: str}
    and a final summary dict:
      {"done": True, "new": int, "changed": int, "removed": int, "failed": int}
    Never raises for a single-item failure — only for something that makes
    the whole course unsyncable (e.g. Canvas auth rejected), which yields
    {"done": True, "error": str} instead of the summary and stops."""
```

Internal shape (not part of the public contract, but pinned here so the
plan can break it into real steps):

1. `db_path = sm_home / "index.lancedb"`; `manifest_path = sm_home / <course
   dir> / "manifest.db"` (matches existing per-course directory convention —
   confirm exact path via `data-model.md` / however `sessions.py` locates a
   course's directory today, during planning).
2. **Files:** `structure = canvas.get_course_structure(course_id)`; filter
   module items where `item.get("type") == "File"` and
   `Path(name).suffix.lower()` (from `get_file()`'s `display_name`) is
   `.pdf` or `.pptx`. Every candidate file needs one `get_file(content_id)`
   call regardless of diff outcome — Canvas's bulk file listing 403s for
   students (`canvas.list_course_files`'s own docstring), so there is no
   cheaper metadata-only listing to diff against first. Build
   `remote_items = [{"id": f"file:{file['id']}", "updated_at": file["updated_at"]}, ...]`.
3. **Pages:** `pages = canvas.list_pages(course_id)`. Build
   `remote_items = [{"id": f"page:{p['url']}", "updated_at": p["updated_at"]}, ...]`.
   (Verify during planning/implementation that `list_pages`'s summary
   objects really do carry `updated_at` without needing `get_page()` first —
   expected per Canvas's documented Pages API, confirm against a real
   course rather than assuming.)
4. Run `sync.diff(conn, "file", file_remote_items)` and
   `sync.diff(conn, "page", page_remote_items)` separately — two calls, two
   item_types, same manifest connection.
5. **Deleted** (either type): `indexing.delete_ref_doc_nodes(db_path, table,
   prefixed_id)`, `sync.forget(conn, prefixed_id, item_type)`, yield
   `{"item": <best-effort name, or the id if unknown>, "status": "done"}`.
6. **Changed**: `indexing.delete_ref_doc_nodes(...)` first — an add-only
   insert without this leaves stale chunks from the old version sitting
   alongside the new ones, since `add_nodes` never replaces. Then treat
   identically to **New**.
7. **New**: download/fetch content, extract, convert to nodes, add to index,
   mark synced:
   - File: download `file["url"]` to a temp path (same `tempfile.mktemp` +
     `httpx.get(..., follow_redirects=True)` pattern
     `generation_smoke_test.py` already uses), `ingestion.extract_pdf` or
     `extract_pptx`, OCR-fallback loop identical to the smoke test's (`if
     p["needs_fallback"]: p["text"] = ingestion.ocr_pdf_page(...)` — PDF
     only, PPTX has no fallback tier today, matching current behavior),
     `indexing.pages_to_nodes(...)` or `slides_to_nodes(...)`.
   - Page: `full = canvas.get_page(course_id, page["url"])`,
     `text = ingestion.extract_html_page(full["body"])`,
     `indexing.pages_to_nodes([{"page": 1, "text": text, "needs_fallback":
     False}], full["title"], f"page:{page['url']}")` — modeled as a
     single-page document; the splitter inside `pages_to_nodes` still
     re-chunks if the page is long.
   - `indexing.add_nodes(nodes, db_path, table_name)`.
   - `sync.mark_synced(conn, prefixed_id, item_type, display_name,
     updated_at, sync.content_hash(extracted_text))`.
   - Yield `{"item": display_name, "status": "done"}`.
8. Any exception raised while processing a single item is caught around
   that item only, yielded as `{"item": display_name_or_id, "status":
   "failed", "error": str(e)}`, and the loop continues to the next item.
9. Final yield: `{"done": True, "new": n, "changed": c, "removed": r,
   "failed": f}`.

`raw_bytes_hash()` (already in `sync.py`) is not used by this phase — it has
no persisted column to compare against yet, and wiring it up is a future
optimization (skip re-extraction when only file metadata changed but bytes
are identical), not required for correctness. Noting this explicitly so it
isn't mistaken for an oversight during review.

### 3.4 `backend/main.py` — one new route

```
SYNC_PATH = re.compile(r"^/courses/(\d+)/sync$")
```

`do_POST` dispatches to a new `_handle_course_sync(course_id)`, gated by the
same `_course_selected()` check every other course-scoped handler uses.
Streams exactly like `_handle_ask`: `Transfer-Encoding: chunked`, one
`_write_chunk()` call per event yielded by `course_sync.sync_course()`,
terminated with `self.wfile.write(b"0\r\n\r\n")`.

```
POST /courses/{course_id}/sync
Response (chunked NDJSON):
  {"item": string, "status": "done"} |
  {"item": string, "status": "failed", "error": string}
  ... one line per processed item ...
  {"done": true, "new": number, "changed": number, "removed": number, "failed": number}
  -- or, if the whole course failed before any items were processed --
  {"done": true, "error": string}
```

### 3.5 Frontend — `app/src/sidecar.ts` + `OnboardingIndexing.tsx`

`sidecar.ts` gets a `syncCourse(courseId, onEvent)` function mirroring
`askQuestion`'s existing NDJSON-over-chunked-fetch parsing loop exactly (same
`ReadableStream` + newline-buffer pattern) — no new parsing logic needed,
just the same shape applied to a different endpoint.

`OnboardingIndexing.tsx` drops its `setTimeout` simulation and `LABELS`
array entirely. It calls `syncCourse` once per course in `courses`
(sequentially, not in parallel — keeps the manifest.db connection usage
straightforward and avoids hammering Canvas with concurrent requests from
multiple courses at once) and renders real per-item events as they arrive.
Exact visual shape (a scrolling list of "✓ syllabus.pdf" style rows? a
progress bar with a count? how failures are shown inline?) is a UI-polish
decision I'll make when implementing this specific piece, the same way the
rest of this app's screens have been iterated on directly rather than
speced pixel-by-pixel in advance. The functional requirement is: the
student can tell it's actually running, sees real names/counts, and sees if
something failed without the screen looking broken.

## 4. Testing

- `backend/tests/test_sync.py`: update any test constructing manifest rows
  or calling `mark_synced()` for the new `display_name` column/parameter.
- New `backend/tests/test_course_sync.py`: unit-test `sync_course()`'s
  branching logic (new/changed/deleted/failed) with `canvas.py`,
  `ingestion.py`, and `indexing.py` mocked/stubbed — this is the first real
  test coverage for orchestration logic that today only exists informally
  in `generation_smoke_test.py`'s manual index-building.
- `backend/scripts/integration_smoke_test.py` is deleted, replaced by a new
  `course_sync_smoke_test.py` that supersedes everything it checked (real
  Canvas course, real files, new → unchanged on a re-diff) and adds real
  coverage it never had: a genuinely changed item (re-synced, old chunks
  gone, new ones present) and a genuinely removed item (deleted from the
  index, not just the manifest) — exercised against real data, not mocks,
  matching this script's own existing house style. Keeping both scripts
  around would just be two overlapping "does Canvas sync work" checks.
- Existing `uv run pytest tests/ -q` gate must still pass in full.
- `backend/README.md`'s section documenting how to run
  `integration_smoke_test.py` gets updated to describe
  `course_sync_smoke_test.py` instead, not left as a dangling reference to
  a deleted file.
- `docs/architecture/overview.md`'s `POST /sync` section is rewritten to
  document the real `POST /courses/{course_id}/sync` contract from §3.4
  (streamed, per-course, triggered by onboarding — not the aspirational
  automatic-on-launch/all-courses design that was never built).

## 5. Open questions to resolve during planning (not blocking spec approval)

- Exact on-disk path convention for a course's `manifest.db` — confirm
  against `data-model.md` / how `sessions.py` or `main.py` currently
  computes a course's directory, rather than assuming.
- Whether Canvas's Pages list endpoint really returns `updated_at` in the
  summary listing (expected, per Canvas API docs) or requires a per-page
  fetch to confirm — resolve against a real course during implementation,
  the same way this codebase's other real findings were confirmed (not
  assumed from documentation alone).
