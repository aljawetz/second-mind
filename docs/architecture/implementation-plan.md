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
**Do:** Embed the Canvas MCP server in the Python backend ([canvas-integration.md](canvas-integration.md));
implement course listing and content fetch for pages, assignments, announcements, and files (via
the module-item workaround for the Files-tab 403).
**Test:** Against a real test course, list courses, fetch a real page and a real assignment.
Replay the known 403/404 cases found this sprint (`list_course_files`, `get_course_structure` on a
restricted section) using the **real responses already captured this session as fixtures** —
confirms graceful degradation without needing live Canvas access on every test run.
**Depends on:** 2.

### 4. Embedding layer (ONNX, torch-free)
**Do:** One-time ONNX conversion of `bge-small-en-v1.5` via `optimum[exporters]` (dev machines
only); a custom `BaseEmbedding` subclass wrapping `onnxruntime` directly, per the corrected design
in [rag-pipeline.md](rag-pipeline.md) §3.
**Test:** Embed a known sentence, confirm the output vector's dimensionality is correct.
Separately: run `pip list` inside the *frozen build's* dependency set and assert `torch` does not
appear — the actual claim this whole design turns on, checked mechanically, not assumed.
**Depends on:** 1. (Independent of Canvas — can run in parallel with 3.)

### 5. Ingestion pipeline (tiered extraction)
**Do:** Real code for Sprint 3's tiered extraction: plain-text → density heuristic
(`chars<100 OR (chars<400 AND has_image)`, [rag-pipeline.md](rag-pipeline.md) §1) → OCR → vision
fallback.
**Test:** Run against the real PDF/PPTX files already captured this session as fixtures (the
Zotero tutorial, the lecture decks, the academic papers) and **assert the extraction character
counts match the numbers already measured** — a real regression test against known-good results,
not a fresh judgment call each time.
**Depends on:** 3 (for new files going forward), but can start immediately against cached fixtures.

### 6. Chunking + indexing (LlamaIndex + LanceDB)
**Do:** Wire ingestion output into LlamaIndex nodes carrying citation-anchor metadata (§2 of
rag-pipeline.md); index into a per-student, per-course LanceDB table.
**Test:** Re-run this sprint's retrieval smoke test as an actual automated test, not a one-off
script — 4 known-answer queries, expect the same 4/4 top-3 hit rate already measured, including
the OCR-dependent one landing at rank 1.
**Depends on:** 4, 5.

### 7. Sync mechanism
**Do:** The manifest diff (new/changed/deleted/unchanged, [design spec](../specs/2026-09-14-ssb-design.md)
§5.5) against real Canvas listings; verify `delete_ref_doc(canvas_item_id)` actually removes the
right chunks (the flagged caveat in [data-model.md](data-model.md) §4 — there's a real open
LlamaIndex issue about this not always working).
**Test:** Simulate a changed item and a deleted item against mocked Canvas responses; confirm the
manifest and LanceDB table end up in the correct state for both, and specifically confirm
`delete_ref_doc` removed exactly that item's chunks and nothing else.
**Depends on:** 3, 6.

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
