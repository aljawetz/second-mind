# Implementation Plan

A sequenced build order with a concrete test for each step — "how do we know this actually works,"
not just "what does it do." Maps to the sprints already in [the design
spec](../specs/2026-09-14-ssb-design.md) §13. **Owner: TBD on every step** — this plan sequences
the work and its dependencies; assigning it to actual team members is separate, still-open work
(see [sprint-04.md](../sprints/sprint-04.md)).

Each step names what it depends on. Steps with no shared dependency can run in parallel once the
team exists to run them in parallel.

## Sprint 5 — Core prototype (ingestion, retrieval, grounded Q&A)

### 0. Project scaffolding
**Do:** Tauri project shell wrapping the existing mockup UI unmodified; a Python backend project
with `pyproject.toml` and a pinned lockfile.
**Test:** `tauri dev` launches and shows the current mockup, unchanged, with no backend wired yet.
**Depends on:** nothing — first task.
**Later revised:** the mockup was ported from vanilla HTML/CSS/JS to React + TypeScript (via Vite)
once step 1's startup gate added real state the manual DOM re-rendering approach didn't carry
cleanly — see [the design spec](../specs/2026-09-14-ssb-design.md) §10. Same visual output, same
Tauri/sidecar wiring underneath; only the frontend's own structure changed.

### 1. Sidecar proof of concept
**Do:** A trivial Python HTTP server (one `/ping` endpoint), frozen via a hand-written PyInstaller
`.spec` file (not the bare `--onefile` flag — [overview.md](overview.md) §3), wired as a Tauri
sidecar with the correct `<name>-<target-triple>` binary naming.
**Test:** The frontend calls `/ping` and gets a real response in *both* `tauri dev` (raw Python
interpreter) and a built `.app` (frozen binary) — proves the dev/frozen path-resolution split and
sidecar wiring work before any real feature is built on top of it.
**Depends on:** 0.
**Real finding:** the webview's native `fetch()` cannot reach the sidecar at all — WKWebView
blocks a plain `fetch()` to `http://127.0.0.1` from the app's custom-scheme origin regardless of
CORS headers, since the request never reaches the webview's network stack. Fixed by using
`tauri-plugin-http`'s `fetch` (routed through Rust via IPC) instead. Separately, an ad-hoc-signed
`.app` (no Apple Developer ID, no notarization — see step 14) took **3.5 minutes** to become
reachable on the very first launch of a freshly built binary, versus ~4 seconds on every launch
after: macOS's Gatekeeper runs a slow scan the first time it sees a given binary hash, then caches
the verdict. This will resolve itself once step 14 lands signing/notarization; until then, the
onboarding startup gate (step 2) has to say so rather than time out.

### 2. Credential storage + onboarding shell
**Do:** Keychain read/write for the Canvas token and LLM key; the 4-step onboarding UI wired to
stub backend calls that validate format only, not real API calls yet. Precedes onboarding: a
startup gate that polls `/ping` before showing any onboarding stage, with copy that escalates to
"first launch can take a minute or two" past 5 seconds of waiting (step 1's finding) rather than
failing fast.
**Test:** Enter test credentials, restart the app, confirm they're still retrievable from Keychain
— not from `config.json` ([data-model.md](data-model.md) §1).
**Depends on:** 1.
**Verified:** real credentials entered via onboarding persisted through a full app restart (fields
came back pre-filled, `Connect →` enabled without retyping), independently confirmed via `security
find-generic-password` and absent from any file on disk. Both Rust (`keyring` crate) and Python
(`keyring` package) read the identical Keychain item directly — no handoff between them, confirmed
by hashing the value read via each independently and getting a match.
**Real finding:** the first-ever Keychain *write* from this ad-hoc-signed build prompted for the
macOS login password — the OS can't recognize a stable app identity across ad-hoc rebuilds, so it
asks for consent rather than silently trusting an unrecognized signer. This is the same root cause
category as step 1's Gatekeeper delay. A real user on a properly signed, notarized build (step 14)
should see this at most once ever, the first time they save a credential; subsequent *reads* did
not re-prompt even after a full app restart on the same (unrebuilt) binary.

### 3. Canvas integration (real calls)
**Do:** A direct Canvas REST API client in the Python backend (`httpx`, sync) — bearer-token auth
from Keychain, `Link`-header pagination — implementing course listing and content fetch for pages,
assignments, announcements, and files (via the module-item workaround for the Files-tab 403), per
[canvas-integration.md](canvas-integration.md).
**Test:** Against a real test course, list courses, fetch a real page and a real assignment.
Capture the known 403/404 cases (`list_course_files`, `get_course_structure` on a restricted
section) as real fixture files, then replay them — confirms graceful degradation without needing
live Canvas access on every future test run.
**Depends on:** 2.
**Verified:** live against the real pilot courses — `list_courses` (12 real courses, confirmed
`StudentEnrollment` role, not elevated access), a real page (course 51113), a real assignment
(course 56350). Both known restriction cases reproduced exactly as documented: `list_course_files`
403s on 56350, `get_course_structure` 403s on 55709 (the other 18654-SV ID succeeds on 55710) —
confirming these are real, current properties of the Canvas API under a student token, not stale
findings. All six responses captured as fixtures (`backend/tests/fixtures/canvas/`) and replayed
via `pytest` + `respx` with zero live calls (6 passed). PyInstaller freezing verified separately —
`httpx`/`keyring` bundle cleanly with no missing hidden imports. Formalized `backend/pyproject.toml`
+ `uv.lock` in the same step, closing a gap from step 0 (never actually done then). Also wired
`GET /courses` (overview.md §2) into the onboarding course-picker (step 2's UI), replacing the
static mock list with the student's real Canvas courses — confirmed working end-to-end in the
running app.

### 4. Embedding layer (ONNX, torch-free)
**Do:** One-time ONNX conversion of `bge-small-en-v1.5` via `optimum[onnx]` (dev machines
only — `optimum[exporters]` named in earlier drafts of this doc isn't a real extra in the
current package); a custom `BaseEmbedding` subclass wrapping `onnxruntime` directly, per the
corrected design in [rag-pipeline.md](rag-pipeline.md) §3.
**Test:** Embed a known sentence, confirm the output vector's dimensionality is correct.
Separately: run `pip list` inside the *frozen build's* dependency set and assert `torch` does not
appear — the actual claim this whole design turns on, checked mechanically, not assumed.
**Depends on:** 1. (Independent of Canvas — can run in parallel with 3.)
**Verified:** 384-dim output confirmed; cross-checked against the sentence-transformers/torch
reference for the same sentence — cosine similarity ~1.0000, the ONNX conversion is numerically
faithful, not just correctly shaped. Confirmed the model's own packaged config has empty
query/document prompts, so no instruction-prefix logic was needed to match what the earlier
retrieval smoke test (4/4 hit rate) already validated. Model files (~128MB, `model.onnx` alone
over GitHub's 100MB push limit) aren't committed — `backend/scripts/convert_embedding_model.py`
regenerates them from the public checkpoint, same reasoning as the gitignored sidecar binary.
**Real finding, caught by the frozen-build check this step explicitly asks for:** building
`ssb-backend` from an environment with `optimum` (dev-only, needed for the ONNX conversion)
installed alongside the runtime deps silently bundled real `torch` submodules into the shipped
binary — PyInstaller bundles whatever's importable in the venv it runs from, not just what
`main.py` actually reaches. Fixed by splitting `backend/pyproject.toml`'s dependency groups
(`build` / `test` / `convert`) so the actual build only ever runs from `uv sync --group build`,
which has no path to torch at all. Confirmed clean on a rebuild from that corrected environment.

### 5. Ingestion pipeline (tiered extraction)
**Do:** Real code for Sprint 3's tiered extraction: plain-text → density heuristic
(`chars<100 OR (chars<400 AND has_image)`, [rag-pipeline.md](rag-pipeline.md) §1) → OCR. Vision
fallback deliberately deferred to step 8, where the pluggable LLM client actually gets built —
`ingestion.needs_fallback()` marks which pages would need it, so the routing logic is real even
though the call itself isn't yet.
**Test:** Run against the real PDF/PPTX files this sprint's docs described but never actually
saved — re-sourced via `canvas.get_file()` and confirmed to be Sprint 3's exact original files
(page/slide counts and character ranges match almost exactly), then **assert the extraction
character counts match the numbers already measured** — a real regression test against
known-good historical results, not a fresh judgment call each time.
**Verified:** `sprint3_zotero_tutorial.pdf` — 11 pages, 1609 total chars, range 6-299 (Sprint 3:
1,614 total, range 6-300); OCR recovers 4925 chars, ~3.06x (Sprint 3: 4,980, "roughly 3x"), in
3.3s for 11 pages. `sprint3_ai_research.pptx` — 15 slides, char range 47-664 (exact match to
Sprint 3), exactly 4 slides with images (exact match). Two more real PDFs (a clean literature
review, 0% flagged; a denser research paper, 20% flagged) extend the regression beyond the
original two files. 15/15 tests pass.
**Real finding:** the plan's fixtures were never actually saved as files — same gap as step 3's
Canvas fixtures, now fixed differently: these are an instructor's real course materials in a
*public* repo, not ours to redistribute, so they're fetched fresh via
`scripts/fetch_ingestion_fixtures.py` (gitignored) rather than committed; only the measured
numbers (`tests/fixtures/ingestion_baseline.json`) are committed, not the files or their
extracted text. `pytesseract` only wraps the `tesseract` *binary* — it won't be bundled by
PyInstaller and needs its own packaging story, deferred to step 14.
**Depends on:** 3 (for new files going forward), but can start immediately against cached fixtures.

### 6. Chunking + indexing (LlamaIndex + LanceDB)
**Do:** Wire ingestion output into LlamaIndex nodes carrying citation-anchor metadata (§2 of
rag-pipeline.md); index into a per-student, per-course LanceDB table.
**Test:** Re-run this sprint's retrieval smoke test as an actual automated test, not a one-off
script — 4 known-answer queries, expect the same 4/4 top-3 hit rate already measured, including
the OCR-dependent one landing at rank 1.
**Depends on:** 4, 5.
**Verified:** the exact original 4 queries were never saved either (same gap as steps 3 and 5),
except one preserved verbatim in rag-pipeline.md ("what citation style should I choose") — reused
here, confirmed by OCR to land on the same real page (8) the original finding described. Three
more queries constructed against real, verified fixture content, including a genuine near-duplicate
pair (pages 3 and 4 are both titled "Installation" with near-identical text) that authentically
reproduces the original's ranking-ambiguity nuance rather than a fabricated one. Result: 4/4 hit
top-3, **all four at rank 1** (the original had one at rank 2) — indexed across all four Step 5
fixtures together (68 nodes), not just the original two files. 19/19 backend tests pass.
**Real findings, two genuine bugs caught only by testing against real dense content and a real
frozen build:**
- `OnnxBgeEmbedding` had no input truncation — a literature-review chunk tokenized past BGE's real
  512-token limit (`max_position_embeddings` in its own config) and crashed onnxruntime outright.
  Fixed with `tokenizer.enable_truncation()`.
- `SentenceSplitter`'s default tokenizer is tiktoken (GPT-style), which (a) doesn't bundle cleanly
  under PyInstaller — its encoding data isn't discoverable frozen — and (b) counts tokens
  differently than BGE's own tokenizer, which is what actually caused the truncation crash above
  (a "700-token" chunk by tiktoken's count isn't 700 tokens to BGE). Fixed at the source by passing
  BGE's own tokenizer to `SentenceSplitter` instead of patching around either symptom.
- Separately: `ssb-backend.spec`'s `datas` was empty — the ~128MB ONNX model was never actually
  wired to be bundled into the shipped binary at all. `embeddings.py` resolves its model path
  relative to `__file__`, which under a frozen build points into the bundle's internal extraction
  path, not `backend/` on disk. This had gone undetected since step 4's own frozen-build check only
  verified dependency imports, not actual model loading — `main.py` didn't import `embeddings.py`
  yet at that point. Fixed by adding the model directory to `datas`; confirmed by actually running
  inference (not just importing) in a frozen build with the fix applied.

### 7. Sync mechanism
**Do:** The manifest diff (new/changed/deleted/unchanged, [design spec](../specs/2026-09-14-ssb-design.md)
§5.5) against real Canvas listings; verify `delete_ref_doc(canvas_item_id)` actually removes the
right chunks (the flagged caveat in [data-model.md](data-model.md) §4 — there's a real open
LlamaIndex issue about this not always working).
**Test:** Simulate a changed item and a deleted item against mocked Canvas responses; confirm the
manifest and LanceDB table end up in the correct state for both, and specifically confirm
`delete_ref_doc` removed exactly that item's chunks and nothing else.
**Depends on:** 3, 6.
**Verified:** 25/25 backend tests pass. `manifest.db`'s diff logic tested against simulated Canvas
listings (`sync.py`); the full changed+deleted flow tested end-to-end against a real LanceDB table
— item_a's old content genuinely gone and replaced, item_b's row genuinely absent, manifest
reflecting both correctly.
**Real finding — the flagged caveat was right, but not for the reason expected.** The GitHub issue
named in data-model.md §4 was filed against `llama-index-core` 0.10.65 (we're on 0.14.24) and
closed via a fix; my first hypothesis was that an unpersisted in-memory docstore was the real risk
for us instead (sync runs once per app launch — a fresh process every time). That hypothesis was
wrong: `VectorStoreIndex.delete_ref_doc` doesn't use the docstore lookup at all — it calls the
vector store's `delete()` directly. The *actual* bug, found by testing directly against a raw
LanceDB table before assuming it was our code: `llama-index-vector-stores-lancedb` 0.6.0 (current
latest, checked PyPI) builds its delete predicate with double quotes
(`doc_id = "x"`), which LanceDB's DataFusion SQL dialect parses as a column reference, not a
string literal — `delete_ref_doc` fails for every input, not just ours. The same broken pattern
(string-concatenated, unescaped double-quoted predicates) also affects `delete_nodes()` and
`get_nodes()` in the same file — confirmed by testing each directly — and is still present on
their `main` branch, not just the release. Worked around with a small
`_PatchedLanceDBVectorStore` subclass overriding `delete()`, using LanceDB's own type-safe
expression API (`lancedb.expr.col`/`lit`) rather than hand-escaping a SQL string — no string
interpolation left to get wrong at all, not just correctly-quoted. Verified against normal IDs,
an ID containing an embedded quote, and an injection-shaped ID (confirmed it matches nothing
rather than matching everything). Also: nothing was setting `ref_doc_id` on nodes at all before
this step — `pages_to_nodes`/`slides_to_nodes` now take a required `canvas_item_id` and wire it
via `NodeRelationship.SOURCE`, which is what both the LanceDB integration's `doc_id` column and
`delete_ref_doc` actually depend on. Reported upstream:
[llama_index#23086](https://github.com/run-llama/llama_index/issues/23086) (issue) and
[llama_index#23087](https://github.com/run-llama/llama_index/pull/23087) (fix PR) — the PR
demonstrates the regression using the package's own existing test suite (bump its lockfile to
current `lancedb`, 3 of 26 tests fail with no code change) before fixing it, and traces the root
cause to [lancedb#3825](https://github.com/lancedb/lancedb/pull/3825), a deliberate breaking
change on LanceDB's side.

### Integration check — everything above, chained together against live data

Every test through step 7 exercises one step in isolation: step 3 replays cached Canvas JSON,
steps 5/6 use cached extraction fixtures, step 7's diff test uses a simulated listing. Nothing had
gone Canvas → extract → embed → index → sync manifest → retrieve as one continuous, live chain.
`backend/scripts/integration_smoke_test.py` does exactly that against a real course (18654-SV,
Software Testing and Operations) — 8 real files, several 40-50 pages, ~150 pages needing OCR
fallback, hundreds of indexed nodes. Result: no seam bugs — every real Canvas item correctly
classified `new` on first sync and `unchanged` on a re-diff against the same live listing (real
`updated_at` timestamps round-tripping through the manifest correctly), and a real retrieval query
("What is a test double and how does Mockito help isolate components?") returned its top 3 results
from the correct file, the top hit directly defining a Mock. Given that every other integration
point checked this sprint (tiktoken bundling, the ONNX model never being wired into `datas`, the
LanceDB delete bug) turned up a real bug, this clean run is itself informative — the seams between
steps 3, 5, 6, and 7 hold.

### 8. Generation (LLM calls + citations)
**Do:** Wire `CitationQueryEngine` + `SimilarityPostprocessor` + a pluggable LLM client selected by
`config.json`'s `llm_provider`.
**Test:** Run real queries against the indexed fixtures from step 6, **with an actual API key** —
this is the one thing untested all sprint because no key was available in this environment. Verify
citations correctly reference the chunks they're attached to, and that a genuinely uncovered
question returns the not-covered response rather than a hallucinated answer.
**Depends on:** 6.

### 9. Q&A frontend wiring
**Do:** Wire the mockup's chat panel to the real `POST /courses/{id}/ask` endpoint
([overview.md](overview.md) §2), including the full error-code handling (§2's error table).
**Test:** Manual end-to-end click-through: ask a real question, see a real cited, streamed answer;
force each error condition (bad key, Canvas unreachable) and confirm the UI shows the right state.
**Depends on:** 8.

## Sprint 6 — End-to-end alpha (session capture, study artifacts)

### 10. Assignment explainer
**Do:** The narrower retrieval + prompt for explain-only behavior, including the topic-level-only
pointer constraint found necessary when testing against a real coding assignment ([design
spec](../specs/2026-09-14-ssb-design.md) §7.1).
**Test:** Re-run the real boundary test from this sprint (the actual social-network unit-testing
assignment) as a scripted test, not a one-off manual exercise — assert the output contains no
per-task-specific implementation language via the proposed cheap output check.
**Depends on:** 8.

### 11. Study artifacts
**Do:** The four artifact types (mock test, mindmap, flashcards, slides) with caching keyed by
course + type + a hash of the content generated from, plus an explicit "regenerate" action.
**Test:** Generate each type once; requesting it again without new content returns the cached
version with no new LLM call; "regenerate" forces a fresh one; adding new synced content surfaces
the "N new items since this was generated" nudge rather than silently invalidating the cache.
**Depends on:** 8.

### 12. Session capture
**Do:** The onboarding schedule editor (with syllabus best-effort pre-fill, [design
spec](../specs/2026-09-14-ssb-design.md) §9.1); app-open window detection (§9.2); recording
start/stop; `faster-whisper` transcription wired to real audio.
**Test:** **A real recording, not synthetic speech** — finally resolving the one gap the synthetic
TTS test couldn't close. A team member records a few minutes of themselves talking naturally, and
the test is real transcription accuracy and speed on that, plus confirming the transcript and
notes get indexed and become askable afterward (closing the loop back to step 9).
**Depends on:** 1, 6.

### 13. Error handling + course removal
**Do:** The full error-code contract (§2 of overview.md) across every endpoint; `unselect` and
`DELETE` for courses as two structurally distinct actions.
**Test:** Force each error condition end-to-end and confirm the exact status/code from the table;
confirm `unselect` leaves `courses/{id}/` untouched and re-selecting resumes without re-indexing
unchanged items; confirm `DELETE` actually removes the LanceDB table, the manifest, and every
session recording.
**Depends on:** 3, 8.

### 14. Packaging, signing, first real build
**Do:** Finalize the PyInstaller spec; Tauri bundle signed and notarized for Gatekeeper.
**Test:** A machine that has never had any dev tooling installed — ideally a teammate's personal
laptop, not the build machine — can install and run the app from the signed `.app` alone.
**Depends on:** everything above.

## What this plan deliberately leaves open

- **Generation faithfulness verification** (does the LLM's answer stay faithful to its cited
  source, not just "was something relevant retrieved") — a real gap named this sprint, not yet
  designed. Worth resolving before step 8 is considered done, not after.
- **Component ownership and who works on what** — this plan sequences and tests the work; assigning
  it to real people is the actual remaining piece of Sprint 4's Implementation and Integration Plan.
- **The offline evaluation harness** for the citation-groundedness-rate success metric (design spec
  §12) — operationalizing "hand-graded on a fixed question set" into an actual repeatable process
  is separate from building the feature itself.
