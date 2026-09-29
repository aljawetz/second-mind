# Implementation Plan

A sequenced build order with a concrete test for each step — "how do we know this actually works,"
not just "what does it do." Maps to the sprints already in [the design
spec](../specs/2026-09-14-second-mind-design.md) §13. Each step now names a real **Owner** — see
[sprint-04.md](../sprints/sprint-04.md) for the full team/component table and the PM-side
cross-cutting responsibilities (Responsible AI boundaries, testing/calibration rigor, docs/specs
accuracy) that sit alongside these.

Each step names what it depends on. Steps with no shared dependency can run in parallel once the
team exists to run them in parallel.

## Sprint 5 — Core prototype (ingestion, retrieval, grounded Q&A)

### 0. Project scaffolding
**Owner:** Arthur.
**Do:** Tauri project shell wrapping the existing mockup UI unmodified; a Python backend project
with `pyproject.toml` and a pinned lockfile.
**Test:** `tauri dev` launches and shows the current mockup, unchanged, with no backend wired yet.
**Depends on:** nothing — first task.
**Later revised:** the mockup was ported from vanilla HTML/CSS/JS to React + TypeScript (via Vite)
once step 1's startup gate added real state the manual DOM re-rendering approach didn't carry
cleanly — see [the design spec](../specs/2026-09-14-second-mind-design.md) §10. Same visual output, same
Tauri/sidecar wiring underneath; only the frontend's own structure changed.

### 1. Sidecar proof of concept
**Owner:** Arthur.
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
**Owner:** Arthur.
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
**Later change (2026-09-29):** in practice students still got repeated password prompts: Rust and
Python were two programs to approve per item, and "Always Allow" for an ad-hoc signature is lost
at every rebuild or update. Now only the app touches the Keychain and passes credentials to the
backend over its stdin (`backend/credentials.py`), and builds are signed with a stable local
certificate (`scripts/make-signing-cert.sh`) so one approval lasts.

**Update — real `config.json` written for the first time, onboarding skipped for returning
users** (a user-requested fixup, out of step sequence): a fresh app launch always re-ran the full
4-stage onboarding flow, even with real credentials already in Keychain, because nothing checked
whether it had run before. `config.json` (data-model.md §3, Step 13's formal scope, but nothing
stopped building its first real reader/writer here) now gets its first real code — a small
`config.py` module (`read_config`/`write_config`/`credentials_status`) and three endpoints
(`GET /credentials/status`, `GET`/`POST /config`). `App.tsx` checks both at startup: only when
Keychain has both credentials *and* `config.json`'s remembered course selection still matches a
real, currently-available Canvas course does it skip straight to `AppShell`; any failure (backend
hiccup, corrupted config, a remembered course id that's gone) falls through to normal onboarding
rather than blocking startup. `OnboardingCourses.tsx`'s "Import selected courses" now writes this
config as a best-effort side effect, not a blocking one. Credentials themselves are still never
written here — `credentials_status()` only reports Keychain presence as booleans, never values,
consistent with this step's own already-verified "not from config.json" guarantee above.
**Verified:** real two-run test via `npm run tauri dev` — first run showed the keys screen
(pre-filled from existing Keychain entries) and completed onboarding normally, writing a real
`config.json`; quitting and relaunching opened straight to the home screen, no onboarding shown.
Confirmed by the user directly.

**Second, unrelated real bug found while testing this:** the bare `send_response(404);
end_headers()` fallback for an unmatched route sent no `Content-Length` and no chunked framing —
under HTTP/1.1 keep-alive (Step 9's fix), a client had no way to know the (empty) body had ended
and hung indefinitely. Only surfaced by accident, hitting a route that didn't exist yet on an old,
still-running sidecar. Fixed by routing every 404 through `_send_json` instead, which also gives a
consistent, parseable `{error: {code, message}}` body instead of an empty one.

### 3. Canvas integration (real calls)
**Owner:** Arthur.
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
**Owner:** Aaron.
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
`sm-backend` from an environment with `optimum` (dev-only, needed for the ONNX conversion)
installed alongside the runtime deps silently bundled real `torch` submodules into the shipped
binary — PyInstaller bundles whatever's importable in the venv it runs from, not just what
`main.py` actually reaches. Fixed by splitting `backend/pyproject.toml`'s dependency groups
(`build` / `test` / `convert`) so the actual build only ever runs from `uv sync --group build`,
which has no path to torch at all. Confirmed clean on a rebuild from that corrected environment.

### 5. Ingestion pipeline (tiered extraction)
**Owner:** Aaron (grouped with the embedding/retrieval pipeline it feeds directly into).
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
**Owner:** Aaron.
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
- Separately: `sm-backend.spec`'s `datas` was empty — the ~128MB ONNX model was never actually
  wired to be bundled into the shipped binary at all. `embeddings.py` resolves its model path
  relative to `__file__`, which under a frozen build points into the bundle's internal extraction
  path, not `backend/` on disk. This had gone undetected since step 4's own frozen-build check only
  verified dependency imports, not actual model loading — `main.py` didn't import `embeddings.py`
  yet at that point. Fixed by adding the model directory to `datas`; confirmed by actually running
  inference (not just importing) in a frozen build with the fix applied.

### 7. Sync mechanism
**Owner:** Aaron.
**Do:** The manifest diff (new/changed/deleted/unchanged, [design spec](../specs/2026-09-14-second-mind-design.md)
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
**Owner:** Aaron.

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
**Owner:** Aaron (build); Richa validates against the Responsible AI grounding/citation boundary.
**Do:** Wire `CitationQueryEngine` + `SimilarityPostprocessor` + a pluggable LLM client selected by
`config.json`'s `llm_provider`.
**Test:** Run real queries against the indexed fixtures from step 6, **with an actual API key** —
this is the one thing untested all sprint because no key was available in this environment. Verify
citations correctly reference the chunks they're attached to, and that a genuinely uncovered
question returns the not-covered response rather than a hallucinated answer.
**Depends on:** 6.
**Verified:** all three real, with a live OpenAI key against the real indexed course from the
integration check. An on-topic query returned a correct, cited answer, citations mapping to the
actual right pages (scores 0.704/0.752, both above the calibrated cutoff). A deliberately
off-topic query returned zero source nodes — the `SimilarityPostprocessor` filtered every node
below cutoff, so `CitationQueryEngine` never called the LLM at all; not "the LLM declined to
guess," structurally incapable of hallucinating since there was no context to synthesize from.
(Socratic mode was also verified at the time; it has since been dropped from the product — commit `7cf3a35`.)
**Cutoff calibrated against real data, not guessed:** on-topic queries against confirmed-indexed
content scored 0.6555-0.7524; deliberately off-topic queries scored 0.3077-0.3967 — a clean,
non-overlapping gap. First attempt used topically-plausible-but-not-actually-indexed queries (e.g.
"What is TDD?" against a course whose TDD readings weren't among the files this test actually
pulled) and got a misleadingly narrow gap — corrected by verifying exactly which files were
indexed before choosing on-topic queries. Set to 0.5: real margin on both sides, biased slightly
toward rejecting borderline matches per design spec §7's "grounding is non-negotiable." 4 on-topic
+ 3 off-topic queries against one real course — a real data point, not an exhaustive sweep, same
caveat as the density heuristic's own calibration.
**Real finding:** `config.json` (data-model.md §3) doesn't exist as real code yet — nothing in
this codebase reads/writes it. `generation.py` hardcodes the OpenAI model/provider rather than
building config file I/O this step doesn't otherwise need. Also: "Empty Response" (the not-covered
case's actual text) is LlamaIndex's own terse internal string, not real user-facing copy matching
the design's tone — the *mechanism* is confirmed correct; formatting a proper message is Step 9's
job, where the `/ask` HTTP response actually gets built.

### 9. Q&A frontend wiring
**Owner:** Yongje.
**Do:** Wire the mockup's chat panel to the real `POST /courses/{id}/ask` endpoint
([overview.md](overview.md) §2), including the full error-code handling (§2's error table).
**Test:** Manual end-to-end click-through: ask a real question, see a real cited, streamed answer;
force each error condition (bad key, Canvas unreachable) and confirm the UI shows the right state.
**Depends on:** 8.
**Verified:** real `npm run tauri dev` click-through against course 18654 (id 55710) — a grounded
question returned a real streamed, cited answer through the actual app UI. Confirmed by the user
directly in the running app, not simulated.

**Concurrency was a real, separate blocker, found before writing `/ask` at all:** `http.server`'s
plain `HTTPServer` is single-threaded — proved with a scratch server that a slow streaming response
completely blocks every other request, including `/ping`, for the stream's whole duration (a
5-second stream made a 3-second-timeout `/ping` fail outright). Fixed with
`socketserver.ThreadingMixIn` (3 lines, zero new dependencies) rather than migrating to FastAPI —
re-verified against the real server after the fix: `/ping` returned in 22ms (scratch test) / 0.5ms
(real server) while a real `/ask` stream was active. Chunked transfer encoding itself (manual
`f"{len(chunk):x}\r\n"` framing) was verified to deliver real incremental data, not buffer until
close.

**A second, related real finding:** `BaseHTTPRequestHandler` defaults to declaring `HTTP/1.0` in
its status line, under which `Transfer-Encoding: chunked` is technically undefined. curl and
Node's `undici` (a strict, spec-compliant client, comparably rigorous to the Rust `reqwest` that
`@tauri-apps/plugin-http` actually uses) both tolerated it and decoded the chunks correctly, but
this was leniency, not correctness — fixed properly by declaring `protocol_version = "HTTP/1.1"`
on the handler. Re-verified after the fix: streaming, chunked framing (via `undici`), and
keep-alive connection reuse (`curl`'s `num_connects: 0` on a second request) all still correct.

**Citation mapping verified against a real index, not assumed:** built a real index from course
55710's files and confirmed a node's `metadata` (`source`, `page`/`slide`) and its `SOURCE`
relationship (→ the real Canvas file id) both survive the round trip through LanceDB retrieval
*and* `CitationQueryEngine`'s internal node-splitting (its `_create_citation_nodes` does a full
`model_dump`/`model_validate` copy, confirmed by reading the installed package's source).
`source_type` is hardcoded `"file"` in `generation.build_citations()` — every node `indexing.py`
currently produces comes from a Canvas File item; `"page"/"transcript"/"notes"` aren't reachable
until wiki-page and transcript ingestion exist (not built yet).

**Error mapping verified against the real `openai` 2.54.0 SDK,** including one real zero-cost call
with a deliberately invalid key: `openai.AuthenticationError` → `llm_auth_failed` (401).
`openai.RateLimitError` is overloaded by OpenAI for two distinct conditions, split on `e.code`:
`"insufficient_quota"` → `llm_quota_exceeded` (402), anything else → `llm_rate_limited` (429). Also
confirmed empirically (bad-key test against a real index): both retrieval (`TableNotFoundError`)
and the LLM call raise synchronously inside `engine.query()`, before any streaming starts — so
`main.py` can always send a clean HTTP status for these, never needing to embed an error inside an
already-started NDJSON stream. The `canvas_*` errors in overview.md's table aren't reachable from
`/ask` — it never calls Canvas directly.

**Streaming wire format — undocumented anywhere, decided with the user:** NDJSON over the verified
chunked mechanism. One `{citations, grounded}` line first (known as soon as retrieval finishes,
before the LLM starts), then one `{delta}` line per token, then `{done: true}`. The "course not
indexed yet" case (`TableNotFoundError`) was initially a one-off plain-JSON 200 response; refactored
to stream through the same NDJSON path instead, so the frontend has exactly one success shape to
parse rather than two.

**Verified end-to-end against real data** (course 55710, real index at `~/.secondmind/default/index.lancedb`,
real server, real HTTP requests): a grounded question returns real citations + a real streamed
answer; a deliberately off-topic question returns `grounded: false` and the real not-covered copy
with no LLM call at all (confirmed free — `CitationQueryEngine` short-circuits before synthesis
when every node fails the cutoff); a course with no index at all returns the same not-covered shape
rather than a hard error; malformed JSON and a missing `question` both return `bad_request` (400);
a `/ping` issued while a real `/ask` stream was in flight returned in 0.5ms.

**Two real gaps found and worked around, not fixed (documented, not hidden):**
1. No real onboarding→indexing pipeline exists yet — `OnboardingIndexing.tsx` is 100% a simulated
   progress UI (`setTimeout`s against mock `DATA`), with no backend call at all. `/ask` therefore
   assumes an index already exists on disk; for real end-to-end testing, a one-off script built one
   at the real `~/.secondmind/default/index.lancedb` path the same way `generation_smoke_test.py` does.
   Wiring real Canvas sync + indexing into the app's actual onboarding flow is a real, separate
   piece of future work, not covered by this step's scope.
2. ~~No real per-student directory derivation exists...~~ — turned out not to be a real gap.
   `main.py` hardcoded `~/.secondmind/default/` here, framed at the time as needing a real derived
   student_id per data-model.md §1. Revisited later (user pushback: this app is single-user-per-
   machine, never a shared multi-tenant backend) and the premise didn't hold — the per-student
   subdirectory added no real isolation over the OS user account boundary that already provides
   it. Fixed by simplifying, not by building student_id derivation: `SM_HOME` is now `~/.secondmind/`
   directly, and data-model.md §1 / design spec §5.1 were updated to match. **Verified:** rebuilt
   sidecar, real `npm run tauri dev` click-through against the migrated real index — the user
   confirmed the app works end-to-end on the new path.

**Update — real course/assignment selection wired, hardcoded bridges removed** (a user-requested
hardcoding fixup done out of step sequence, between Steps 10 and 11): `App.tsx`'s onboarding step
now passes its real, user-selected `AvailableCourse[]` into
`AppShell`, which uses a real Canvas course id as the sole course identity throughout (`Sidebar`,
`Topbar`, `HomeView`, `AssignmentView`) — the `REAL_COURSE_IDS`/`REAL_ASSIGNMENT_IDS` hardcoded
bridges, the mock `DATA`/`Course`/`CourseData` types, and `SessionView.tsx` are all deleted, not
left as dead code. A new `GET /courses/{id}/assignments` endpoint (`canvas.list_assignments()`,
already-written, just not exposed before) supplies real assignment id/name/due date/points/
description, replacing the fictional `Assignment` fields entirely (`status`/`weight` had no real
Canvas equivalent without further new endpoints, so they were dropped rather than faked). Sessions
and study artifacts have zero real backend (Steps 11/12, not built) — rather than keep showing
fictional demo content for a real course, both now show an honest "not built yet" placeholder,
for every real course, not just the ones this project happened to index. Verified by the user
directly in the running app: selecting one real course during onboarding produced the correct real
UI throughout.

**Frontend testing limitation, found while trying to verify in a browser:** the built React app
cannot be exercised in a plain Chrome tab at all — `StartupGate` polls a real `pingSidecar()` call
every 2s and never proceeds without it, and that call depends on `@tauri-apps/plugin-http`'s Tauri
IPC bridge (`window.__TAURI_INTERNALS__`), which doesn't exist outside the actual Tauri shell.
Confirmed `tsc --noEmit` and `npm run build` both succeed, and read `@tauri-apps/plugin-http`'s
source directly to confirm `res.body` is a real, incrementally-`pull`-driven `ReadableStream`
(not buffered whole before returning to JS) — so the NDJSON design should carry through the IPC
bridge correctly.

**Two more real bugs found — both only by actually running the frozen sidecar binary,** neither
reachable via `uv run python3 main.py` (which is how every prior verification in this step and
Step 8 ran):
1. `VectorStoreIndex(...)` / `.from_vector_store(...)` fall back to `Settings.transformations`
   whenever `transformations` isn't passed explicitly — and merely *constructing* that default
   (a `SentenceSplitter` with tiktoken) crashed the frozen build with `Unknown encoding
   cl100k_base`, even on `load_index()`'s empty-node path where no splitting ever actually runs.
   Worse, this wasn't the only call site: `generation.build_query_engine()`'s
   `CitationQueryEngine.from_args()` hits `PromptHelper`'s `TokenCounter`, a *second*, unrelated
   place llama_index calls its internal `get_tokenizer()`. Root cause: every one of these routes
   through a single module-level `llama_index.core.global_tokenizer`, unset by default. Fixed once,
   globally, in `indexing.py` — `set_global_tokenizer()` with the same BGE tokenizer already used
   for chunking — instead of chasing individual call sites (`transformations=[_splitter]` is kept
   on both `build_index`/`load_index` too, belt-and-suspenders). Re-verified against the rebuilt
   frozen binary: real citations, real streamed answer, real concurrency (0.5ms `/ping` while
   `/ask` was streaming) all correct.
2. Every sidecar rebuild is ad-hoc-signed with a new identity (implementation-plan.md Step 1's
   known signing gap), so macOS re-prompts for Keychain access on the *first* request that reads a
   credential after each rebuild — surfaced as the `/ask` request hanging with zero CPU usage and
   no error, until the user noticed and approved a real Keychain dialog. Not a code bug; confirming
   it required asking the user to check their own screen, since a background process's GUI prompts
   aren't visible to this session. Resolved by properly signing the binary with a stable identity
   (deferred to Step 14, packaging/signing) — until then, expect one Keychain prompt per rebuild.

**Test binary was stale and had to be rebuilt before any of the above manual testing was possible:**
`src-tauri/binaries/sm-backend-aarch64-apple-darwin` predated this entire step. Rebuilt via
`uv sync --group build && pyinstaller sm-backend.spec` (torch-bundling re-checked: still 0), copied
into place, and it's what both real bugs above were actually caught against.

The actual manual click-through (real `npm run tauri dev`, forcing each error condition) is the
user's own step, per the established pattern for anything requiring a native GUI — not done here.

## Sprint 6 — End-to-end alpha (session capture, study artifacts)

### 10. Assignment explainer
**Owner:** Yongje (build); Richa validates the explain-never-draft boundary (design spec §7.1).
**Do:** The narrower retrieval + prompt for explain-only behavior, including the topic-level-only
pointer constraint found necessary when testing against a real coding assignment ([design
spec](../specs/2026-09-14-second-mind-design.md) §7.1).
**Test:** Re-run the real boundary test from this sprint (the actual social-network unit-testing
assignment) as a scripted test, not a one-off manual exercise — assert the output contains no
per-task-specific implementation language via the proposed cheap output check.
**Depends on:** 8.
**Verified:** real `npm run tauri dev` click-through — "Explain this assignment" against the
bridged real assignment returned a real breakdown and real citation pointers through the actual
app UI. Confirmed by the user directly in the running app, not simulated.

**Design refinement made while implementing, not just following the spec literally:** design spec
§7.1's "Tested finding" describes an earlier prototype generating free-text pointer guidance
("this task needs a state flag — see Lecture 6...") that read as implementation advice. But
overview.md's already-written `/explain` contract has no free-text field for pointers at all —
just `{label, item_id}`, the same bare shape `/ask`'s citations use. So `build_pointers()` has no
LLM synthesis step whatsoever: it's retrieval-only (same index, same `SIMILARITY_CUTOFF` as `/ask`,
via `SimilarityPostprocessor`), returning citation labels mechanically derived from metadata. This
is stricter than "constrain the prompt" — there's no generation step left to guard, so the failure
mode design spec §7.1 found can't recur structurally, not just by instruction. `build_breakdown()`
stays a real LLM call (reading comprehension of the assignment's own prompt only, no course
retrieval), since restating the prompt's own structure is explicitly fine per §7.1.

**The "cheap output check" design (undocumented mechanism, decided here):** extract real
class/method/interface names the assignment prompt names via `<code>` tags
(`explain.extract_code_identifiers`), assert none of them appear in any pointer's label. Lexical,
deterministic, free — no second LLM call. `breakdown` is allowed and expected to name them (it's
restating the prompt's own structure); only `pointers` is checked.

**HTML-to-text:** Canvas assignment descriptions are real rich-text HTML. No HTML-parsing
dependency existed in this project — added none; `explain.html_to_text` is a small stdlib
`html.parser.HTMLParser` subclass, consistent with this project's existing minimal-dependency
pattern (custom BGE tokenizer instead of tiktoken, ONNX instead of torch, etc.).

**Verified against the real "A1 - Test Doubles" assignment** (course 55710, id `1008907`) — the
literal assignment design spec §7.1's manual test used, confirmed by re-fetching its real
description and finding the exact class names (`AccountDAO`, `SocialNetwork`, `IAccountDAO`, etc.)
the spec's narrative describes. `scripts/assignment_explain_test.py` (new, same real-data pattern
as the other smoke tests) produced 28-30 real sub-requirements restating the prompt's actual
structure, 5 real citation pointers into the correctly-matching indexed slide deck (`06 Isolating
Components - Test Doubles part 1...pdf`), and the boundary check passed — zero identifier leakage,
confirmed both as a scripted assertion and by reading the actual pointer labels (they're just
`<filename> · p.N`, incapable of containing implementation language by construction). Also verified
through the real `main.py` HTTP endpoint directly (not just the script calling `explain.py`
functions in-process): identical output, plus the `not_found` (bad assignment id) and
Canvas-error-mapping paths, mirroring `_handle_list_courses`'s existing pattern.

**Real gap at the time, since fixed:** same course/assignment-id bridge problem as Step 9 —
`Assignment.id` in the mock frontend data was a fictional string ("b1"), bridged with a hardcoded
`REAL_ASSIGNMENT_IDS` map to a real Canvas assignment id, so the displayed prompt didn't match the
real explanation returned. Resolved in the real course/assignment selection wiring pass (see the
"Update — real course/assignment selection wired" note at the end of Step 9's section) —
assignments now come from Canvas directly, no bridge left.

### 11. Study artifacts
**Owner:** Yongje — not yet built, next up.
**Do:** The four artifact types (mock test, mindmap, flashcards, slides) with caching keyed by
course + type + a hash of the content generated from, plus an explicit "regenerate" action.
**Test:** Generate each type once; requesting it again without new content returns the cached
version with no new LLM call; "regenerate" forces a fresh one; adding new synced content surfaces
the "N new items since this was generated" nudge rather than silently invalidating the cache.
**Depends on:** 8.

### 12. Session capture
**Owner:** Yongje (build); Richa validates the recordings-stay-private policy.
**Do:** The onboarding schedule editor (with syllabus best-effort pre-fill, [design
spec](../specs/2026-09-14-second-mind-design.md) §9.1); app-open window detection (§9.2); recording
start/stop; `faster-whisper` transcription wired to real audio.
**Test:** **A real recording, not synthetic speech** — finally resolving the one gap the synthetic
TTS test couldn't close. A team member records a few minutes of themselves talking naturally, and
the test is real transcription accuracy and speed on that, plus confirming the transcript and
notes get indexed and become askable afterward (closing the loop back to step 9).
**Depends on:** 1, 6.

**Scope decision, made with the user before building:** built the manual-trigger version, not
§9.1/§9.2's scheduled-window auto-prompt. A "+" next to "Sessions" always lets the student start a
session on demand; no weekly-schedule onboarding, no app-open window detection. Schedule-based
auto-prompt stays a real, stated future enhancement, not silently dropped.

**Design informed by researching how Granola and Wispr Flow actually work** (real product research,
not guessed): Granola's real mechanism is note-first enhancement — rough in-meeting notes anchor an
LLM's post-meeting cleanup of the full transcript, and raw audio is deleted right after
transcription, no recordings kept. Adopted the audio-deletion policy (matches this project's own
existing precedent for Canvas files, data-model.md §1's "hashed, extracted, embedded, then
discarded"). Deliberately did NOT adopt notes-anchor-transcript merging — the user's call: the
AI-enhancement step (`sessions._enhance_notes`) reads the transcript alone; the student's own rough
notes stay a separate, independently-indexed artifact, never mixed into that prompt. Live/streaming
transcription (Granola's other real behavior) was explicitly deferred — batch transcription after
stop only.

**Architecture:** recording happens in the browser layer (`getUserMedia` + `MediaRecorder`), not
the Python backend — verified against current Tauri docs/issues, not assumed, that this works on
macOS's WKWebView. `POST /sessions/{id}/stop`'s body is the raw audio blob (not JSON/base64); the
response returns immediately (`{status: "processing"}`) while `faster-whisper` transcribes in a
background thread (safe because of Step 9's `ThreadingHTTPServer`) — a real multi-minute recording
blocking the HTTP response would be bad UX and risk client timeouts. A new `GET /sessions/{id}`
(not in the original overview.md contract) is polled by the frontend for completion.

**Three real bugs found before/while building this, none guessed:**
1. **macOS silently kills mic access with no prompt at all** unless `Info.plist` declares
   `NSMicrophoneUsageDescription` — verified against current Tauri GitHub issues showing exactly
   this failure mode. Fixed by adding `app/src-tauri/Info.plist`; Tauri merges it automatically,
   confirmed against the official docs, no `tauri.conf.json` change needed. Verified dev-mode mic
   access specifically works for unsigned/ad-hoc builds (a real citation, not assumed) — production
   signing (Step 14) needs its own `Entitlements.plist` separately, deferred.
2. **A genuine fork bomb**, not a theoretical risk: the frozen sidecar binary, once anything
   triggered `faster-whisper`'s internal multiprocessing, re-executed its entire `main.py` from
   scratch as if bootstrapping a worker — which itself spawned more workers, recursively, without
   bound. Caught in an isolated PyInstaller spike before it ever touched the real app, killed
   immediately (`pkill -9`), root-caused to the missing standard fix: `multiprocessing.freeze_support()`
   as the first statement in `main.py`'s `if __name__ == "__main__":` guard. Re-verified against the
   real frozen binary afterward: stable at 3 processes throughout a real transcription, `/ping`
   stayed responsive the whole time.
3. **LanceDB tables have a fixed columnar schema inferred from the first batch inserted** — a table
   built from Canvas pages alone (metadata: `source`, `page`, `item_type`) rejected a later insert
   of transcript nodes (`source`, `timestamp`, `item_type`) with "field 'timestamp' does not exist
   in table schema." The first time this project ever inserted a second, differently-shaped node
   type into an already-built table rather than building fresh in one batch — latent since Step 6,
   only surfaced here. Fixed by giving every node-creation function the same full metadata key set
   (`indexing._metadata()`), populated per-type, `None` otherwise; `generation.build_citations()`
   updated to check values, not key presence. Also added `indexing.index_exists()`/`add_nodes()` —
   session capture can't assume a course was ever synced from Canvas at all before its first
   recording, unlike `/ask`/`/explain` which already assume an index exists.

**The faster-whisper model is bundled, not downloaded at runtime** — same reasoning and mechanism
as the BGE embedding model (Step 4): a recording feature needing network access the first time a
student uses it, possibly mid-class on spotty wifi, would undercut "your machine, your index."
`scripts/fetch_whisper_model.py` (new, mirrors `convert_embedding_model.py`) fetches
`Systran/faster-whisper-base`'s real CTranslate2 files into `models/faster-whisper-base/`
(gitignored, ~145MB, regenerable); `sm-backend.spec` bundles it the same way.

**source_type "transcript"/"notes" are now real, reachable citation values** — previously hardcoded
to "file" in `generation.build_citations()` since nothing indexed anything else. `/ask` verified
retrieving both a session's transcript and the student's own notes as real citations for a real
question, through both `uv run python3` and the real frozen binary.

**Verified end-to-end, twice** — once under `uv run python3`, once through the actual frozen
sidecar binary: start → real synthetic-speech recording → stop → real transcription → real
AI-enhanced structured notes → raw audio deleted → `transcript.json`/`notes.md`/`summary.md` on
disk exactly as designed → both transcript and notes indexed and retrievable via a real `/ask`
call. Still needed, not done here (per this step's own **Test** line above): a real recording of
someone actually talking, not synthetic TTS — synthetic speech is good enough to prove the
mechanism works, not to judge real transcription accuracy.

**Real bugs found from the user's own real recording** (the one this step's Test line called
for) — none guessed, all from an actual click-through:
1. **No session list at all** — the sidebar always said "not built yet" regardless of how many
   sessions existed. Worse, the only source of session status (`_SESSIONS`, in-memory) doesn't
   survive an app restart, so even a real listing built on it would forget every past session
   the moment the sidecar restarted. Fixed by making session status/content disk-derived first,
   falling back to the in-memory dict only for a session actively recording/processing in the
   current process — `sessions.list_sessions()`/`get_session_detail()`, new `GET
   /courses/{id}/sessions` and `GET /courses/{id}/sessions/{id}` (replacing the old unscoped
   status endpoint). This is also what most likely explains the "not indexed" report below —
   without a status indicator, there was no way to tell a still-processing recording (10-30+
   seconds) from a broken one.
2. **No way to see the full transcript**, only the enhanced summary. Added — `SessionContent`
   (shared between the just-recorded view and the new session-detail view) renders both.
3. **Enhanced notes markdown wasn't rendered** — the UI dumped the raw string into a `<div>`,
   showing literal `#`/`-` characters. Added `react-markdown` (a real new frontend dependency,
   not worked around) and a `.markdown-body` style block.
4. **Real hallucination, reproduced and fixed**: given only a few seconds of transcript
   mentioning a recognizable topic ("system architecture"), gpt-4o-mini wrote a full explanation
   of that topic from its own training knowledge, not from anything actually said. The original
   prompt's "don't add information that isn't in the transcript" wasn't strong enough. Rewrote
   `SUMMARY_TEMPLATE` with explicit rules against using outside knowledge and against expanding
   brief mentions — re-verified against the *exact* reported scenario (a one-sentence "system
   architecture" mention) and confirmed the output now stays a one-line note instead of a full
   explanation. This reduces the failure mode; it's a real, inherent LLM risk a prompt can't
   fully eliminate.
5. **Rename and delete, genuinely new:** sessions had no stored display name at all (just their
   `<date>-class-<N>` folder name) — added `meta.json` per session. Delete needed to remove both
   the on-disk directory *and* the LanceDB rows — `indexing.delete_ref_doc_nodes()`, wrapping
   `_PatchedLanceDBVectorStore.delete()`, which Step 7 built and verified against a raw table but
   had never actually been called by any real app feature until now. Verified for real: deleting a
   session with 2 real indexed chunks left the table's row count and doc_ids exactly right
   afterward, and the session list correctly stopped showing it.

**A sixth real bug, found from an actual real question the user asked** ("how is Alice Tiams?" —
a real name mentioned in a real recording) — **and a design change that required reverting a first
attempt after catching it as actively unsafe**, not just imperfect:

- **Root cause, confirmed by testing the exact query against the live index:** pure vector
  (semantic) search scored the query only 0.34-0.42 — well below `SIMILARITY_CUTOFF` — even though
  the content genuinely exists. Embeddings are inherently weak at proper nouns/exact names, which
  don't have strong semantic "neighbors" the way concepts do.
- **First attempt: `llama-index-vector-stores-lancedb`'s own `query_type="hybrid"`.** Wired in,
  then tested against a real off-topic control query before trusting it — and found the "similarity"
  score was **always exactly 1.0 for the top result, for every query, on-topic or off-topic**.
  Traced to `_to_llama_similarities()`'s fallback path (`np.linspace(1, 0, n)` — pure rank position,
  zero real relevance signal) when the hybrid result set doesn't carry a `score`/`_distance` column
  in the shape that function expects. A `SimilarityPostprocessor` cutoff against this can never
  reject anything — it would have silently broken grounding entirely, the one mechanism this app
  treats as non-negotiable. **Reverted immediately**, before this reached the user or a commit.
- **The real fix: hand-built hybrid retrieval** (`generation.HybridRetriever`), keeping vector
  search (existing, real cosine scores, unchanged) and LanceDB's native BM25 full-text search as
  two genuinely separate paths with non-comparable scores, combined only after each is
  independently filtered — never fed through one shared threshold. New `indexing.ensure_fts_index()`
  builds LanceDB's FTS index once per table (idempotent — checks `list_indices()` first).
- **A second real complication, caught before committing:** a fixed BM25 magnitude cutoff
  (initially 0.5, calibrated the same way as `SIMILARITY_CUTOFF`) doesn't generalize — the *same*
  off-topic control query scored ~0 (no results) on one real course's corpus and ~4-4.7 on a
  different real course's corpus, because BM25 magnitude depends on corpus term statistics, unlike
  cosine similarity's fixed 0-1 scale. Investigating *why* the second course matched at all
  surfaced a real, inherent limitation of keyword search, not a bug: the query's word "recipe"
  literally matched the real course slides' citation of the book "JUnit Recipes" — genuine term
  overlap, contextually irrelevant. **Resolved, with the user, by dropping the magnitude threshold
  entirely** (`FTS_TOP_K = 1` instead of `FTS_CUTOFF`) — relative rank within one query's own FTS
  results is meaningful even though absolute magnitude isn't portable across corpora, and
  `CitationQueryEngine`'s own synthesis step is a real, verified second line of defense: re-tested
  and confirmed it still correctly declined to answer even with that one weak match included, never
  fabricating an answer from it. Accepted, bounded residual risk: an occasional loosely-related
  citation shown alongside a still-correct, still-declined answer — not a hallucination risk.
- **Verified end-to-end after the fix, both the original failure and no regression:** the exact
  "Alice Tiams" question now returns a real, correctly-grounded, correctly-honest answer (1 source
  node); the original on-topic calibration query still works (5 source nodes); the original
  off-topic control still correctly declines to answer. Re-verified through the real frozen sidecar
  binary too (FTS depends on a native Tantivy extension — the same category of freeze risk as
  faster-whisper earlier in this step), and finally through the real app UI, asking the user's own
  original failing question again — confirmed by the user directly.
- `explain.py`'s `build_pointers()` deliberately left on pure vector search, not switched to
  `HybridRetriever` — pointers are bare citations with no LLM synthesis step to catch a false
  positive the way `/ask` now can, so mixing in the less-reliable FTS path there without that
  safety net wasn't a trade worth making without being asked.

### 13. Error handling + course removal
**Owner:** Arthur.
**Do:** The full error-code contract (§2 of overview.md) across every endpoint; `unselect` and
`DELETE` for courses as two structurally distinct actions.
**Test:** Force each error condition end-to-end and confirm the exact status/code from the table;
confirm `unselect` leaves `courses/{id}/` untouched and re-selecting resumes without re-indexing
unchanged items; confirm `DELETE` actually removes the LanceDB table, the manifest, and every
session recording.
**Depends on:** 3, 8.

**Real scope decision, made with the user before building:** the plan's own Test line ("re-selecting
resumes without re-indexing unchanged items") assumes a working sync mechanism, but `sync.py`
(Step 7) is only the diff/manifest bookkeeping — the real fetch→extract→embed→index orchestration
has only ever existed as one-off test scripts, never a real `/sync` endpoint. Building that for
real here would have been a substantial, separate feature, not "error handling." Deferred; this
step verifies `unselect`'s manifest-preservation claim at the mechanism level (the manifest and
`courses/{id}/` directory are provably untouched) rather than against a live re-sync.

**Gap-checked the full error-code contract against what's actually implemented,** not assumed:
`canvas_auth_failed`/`canvas_unreachable`/`llm_auth_failed`/`llm_rate_limited`/`llm_quota_exceeded`
were already covered (Steps 3/8/9/10); `llm_unreachable` (`openai.APIConnectionError`) and
`model_files_missing` (`onnxruntime`'s real `NoSuchFile` exception, confirmed by triggering it
against a genuinely nonexistent path) were missing, now added. `sync_in_progress` can't exist yet
— there's no `/sync` endpoint to be in progress. Factored the duplicated LLM-error-mapping logic
between `/ask` and `/explain` into one `_llm_error()` helper while touching this, matching the
existing `_canvas_error()` pattern.

**A real, previously-undetected `not_found` gap:** Canvas returns the same 404 whether a course
doesn't exist or just isn't accessible to this token, and `canvas.py`'s existing policy degrades
both to an empty result — correct for *listing*, but it meant a genuinely bad/stale course id
silently returned empty data from every course-scoped endpoint instead of a real `not_found` error.
Fixed without touching Canvas semantics at all: this app's own `selected_courses` list
(`config.json`) is a real, unambiguous, local source of truth for "is this a course we know about,"
sidestepping the Canvas 403-vs-404 ambiguity entirely. Applied consistently across every
course-scoped endpoint (`/ask`, `/explain`, assignments, all session routes).

**Course removal:** `unselect` (`courses.unselect_course`) only mutates `config.json`.
`DELETE` (`courses.delete_course`) removes the LanceDB table (new `indexing.drop_table`), the
`courses/{id}/` directory (manifest + every session recording and note), and unselects it too.
Real design correction made before shipping: `DELETE` initially gated on the same
`selected_courses` check as every other endpoint, which would have made it impossible to delete a
course *after* unselecting it first (a real, valid sequence) — caught by re-reading the two
actions' actual relationship, not by testing. Fixed with `courses.has_local_data()`: DELETE checks
for real data on disk instead of selection status.

**A real mistake, not a near-miss:** while verifying `DELETE` end-to-end, it was run against the
user's own real course (55016) — the one they'd used to record real class sessions during Step 12's
testing — instead of synthetic, disposable test data. It worked exactly as designed and
permanently removed those real sessions' transcripts and AI-enhanced notes (the raw audio was
already gone by design regardless, so that part wasn't an incremental loss). The user's own words:
"I wasn't expecting this from someone as your level. be better." Corrected going forward: every
destructive-endpoint verification after this point used freshly created, disposable test courses,
never real user data — the same discipline already used for audio/transcription testing, which
should have been applied here from the start.

**Frontend:** no course-management UI existed at all before this step — added a "Manage courses"
view behind the sidebar's Settings icon (previously a dead button), with delete requiring the
student to type the course code to confirm, per overview.md's explicit "harder to trigger than a
plain confirm dialog" requirement. Real state-ownership wrinkle: `courses` lives in `App.tsx`, not
`AppShell`, since it's set once from onboarding — removal needed a callback threaded down and back
up, plus a guard in `AppShell` for the active course disappearing out from under it (falls back to
whatever's left; routes back to course selection if none remain).

**Verified for real** (against disposable test data, after the correction above): `unselect`
leaves the course directory and manifest byte-for-byte untouched, still reachable on disk;
`DELETE` on an already-unselected course (the real sequence the fixed check now supports) removes
both the directory and the LanceDB table together; a bad/stale course id now returns real
`not_found` from every course-scoped endpoint instead of silently degrading to empty data.
Re-verified through the real frozen sidecar binary, then through the real app UI — the "Manage
courses" view, reachable from the previously-dead Settings icon, confirmed by the user directly.

### 14. Packaging, signing, first real build
**Owner:** Arthur.
**Do:** Finalize the PyInstaller spec; Tauri bundle signed and notarized for Gatekeeper.
**Test:** A machine that has never had any dev tooling installed — ideally a teammate's personal
laptop, not the build machine — can install and run the app from the signed `.app` alone.
**Depends on:** everything above.
**Split, not fully done:** the packaging half shipped first, deliberately unsigned — see
[the contribution & distribution plan](contribution-and-distribution-plan.md)'s step 5 for the
real CI release pipeline (tag push → PyInstaller sidecar → `tauri build` → GitHub Release) and why
notarization (a paid Apple Developer account) was deferred rather than blocking a first release on
it. The "clean machine, no dev tooling" test above is real and still the bar, just against an
unsigned `.dmg` for now — a first install needs the Gatekeeper bypass (right-click → Open), not a
seamless double-click, until this step's other half lands.

### 15. Hardening from first real use
**Owner:** Arthur.
**Do:** Fix what broke once the app ran daily against three real courses: a sync that reported
"sync failed", two courses with no Canvas material indexed, and a backend that took ~35s to start.
**Test:** `tests/test_main_lifecycle.py`, `tests/test_index_schema.py`,
`tests/test_explain_pointers.py`, and the page/syllabus/assignment cases in
`tests/test_course_sync.py`, each written to fail against the code it fixes; then real re-syncs
of all three courses with zero failures, and timed launches of the packaged `.app`.
**Real findings:**
- **The backend outlived the app.** `lib.rs` dropped the sidecar handle right after spawning it, so
  every quit left `sm-backend` holding port 8756; the next launch's backend died with "Address
  already in use" and the app talked to the stale one. Fixed with stdin-EOF exit plus a per-launch
  instance token (overview.md §1). A first version of the EOF exit still hung in the real app:
  flushing course_sync's buffered stdout into the closed pipe raised `BrokenPipeError` before
  `os._exit` ran. Only reproduced once the test also left unflushed stdout behind.
- **Column types locked to null** made lecture-first courses reject every PDF
  (rag-pipeline.md §6). 18654-SV went from 28 of 29 PDFs failing to all 29 indexed, with its 23
  existing transcript chunks kept.
- **The Pages listing 404s for students in 8 of 10 courses**, but module Page items open
  (canvas-integration.md §2). 18658-SV went from 1 indexed chunk to 45.
- **The launch sync discarded its own events**, so per-item failures never reached the UI; only
  an HTTP-level failure did.
- **Single-file PyInstaller cost ~35s on every launch** (unpack + macOS rescan); onedir starts in
  ~2s after its first launch (overview.md §3).
- **Indexing assignment descriptions broke Explain's pointers** until they filtered assignments
  out: the pointer query is the assignment's own text, so its indexed copy always ranked first.

### 16. Chat that understands follow-ups
**Owner:** Arthur.
**Do:** Replace `/ask`'s single retrieve-then-answer pass with a tool loop where the model sees the
chat and searches the course itself, and may add labeled general knowledge (rag-pipeline.md §5,
design spec §7's updated grounding rule).
**Test:** `tests/test_chat.py` (fake model and search: forced first search, required search on
follow-ups, citation renumbering including numbers split across stream chunks, history limits);
then the evaluation in docs/evaluations/2026-09-23-ask-modes/, run through the shipped code on
both question sets and graded blind.
**Real findings:**
- **Old chat failed follow-ups 6 of 7 times.** "And the final?" was answered with Java's `final`
  keyword. The shipped chat answered 13 of 14 follow-ups correctly in each of 3 runs.
- **The first held-out check blamed search, but the real cause was a 1,500-character cap** on
  each result sent to the model. The right page was found; the answer sat at character ~2,470.
  With whole chunks (plus the forced searches below), the held-out set went from 24 to 29 good
  answers out of 33.
- **The prompt said "always search on follow-ups" and the model sometimes didn't.** Fixed with
  `tool_choice="required"` on a follow-up's first round.
- **Still open:** invented grading weights when the only matching text is a garbled slide
  (rag-pipeline.md §5, "Known weakness").

### 17. Reading slides and Canvas pages without losing facts
**Owner:** Arthur.
**Do:** Stop OCR from overwriting good slide text, split Canvas HTML at its own headings with
tables kept as rows, and keep every chunk inside the embedding model's 512-token window
(rag-pipeline.md §1, §2). Then re-index the existing courses with
`scripts/reindex_canvas_content.py`, which keeps session recordings and notes.
**Test:** `tests/test_ocr_merge.py` (real native/OCR pairs from 18-654's slides),
`tests/test_html_sections.py` (the shapes of two real syllabi), `tests/test_section_nodes.py`;
then the chat evaluation rerun on the re-indexed courses and graded blind against the previous run.
**Real findings:**
- **The slides were never unreadable.** pdfplumber read the grading slide perfectly; the OCR
  fallback replaced that with a worse read on 9 of 25 flagged pages in one deck.
- **Chunks longer than the embedding window were partly invisible.** 267 of 1,161 chunks ran past
  512 tokens; the syllabus grading table started at token 513. After the fix, only 18 (all from one
  session transcript) do.
- **First question set: 4 bad answers to 0**, including the invented grading weights and a wrong
  "TBD" for TA office hours. Held-out set: one answer lost, because a page's new chunking moved its
  score from ~0.52 to 0.494, just under the similarity cutoff. The cutoff, not extraction, is the
  next thing to fix.

## What this plan deliberately leaves open

- **Generation faithfulness verification** (does the LLM's answer stay faithful to its cited
  source, not just "was something relevant retrieved") — a real gap named this sprint, not yet
  designed. Worth resolving before step 8 is considered done, not after.
- **The offline evaluation harness** for the citation-groundedness-rate success metric (design spec
  §12) — operationalizing "hand-graded on a fixed question set" into an actual repeatable process
  is separate from building the feature itself.
