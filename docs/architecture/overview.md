# Architecture Overview

Sprint 4 detail behind [the design spec](../specs/2026-09-14-ssb-design.md)'s §5 architecture.
This document covers the end-to-end system shape, component interfaces, deployment, security, and
reliability. Four companion documents go deeper on specific layers:

- [Data model](data-model.md) — on-disk folder structure, what's stored where, how a course's
  weekly schedule is represented.
- [Canvas integration](canvas-integration.md) — which endpoints we use, the access restrictions
  found in Sprint 3, and how §5.5's sync mechanism maps to real API calls.
- [RAG pipeline](rag-pipeline.md) — ingestion, chunking, embedding, hybrid retrieval, and LLM
  calls, including where OpenAI/Anthropic/etc. actually get invoked.
- [Implementation plan](implementation-plan.md) — the actual build order: 15 sequenced steps
  across Sprint 5–6, each with its dependencies and a concrete test.

## 1. Shape of the system

SSB is a single native desktop app, not a client talking to a server SSB operates. Two processes
run on the student's machine:

```
┌───────────────────────────────────────────────────────────────────┐
│ SSB.app (Tauri, macOS)                                            │
│                                                                    │
│  ┌─────────────────────────┐        ┌──────────────────────────┐ │
│  │ Frontend                │  HTTP  │ Local backend             │ │
│  │ Tauri webview            │◄──────►│ Python, bound to          │ │
│  │ (the existing HTML/CSS/  │  JSON  │ 127.0.0.1 only            │ │
│  │  JS mockup, adapted)     │        │ FastAPI or equivalent     │ │
│  └─────────────────────────┘        └──────────┬───────────────┘ │
│                                                  │                 │
│                    ┌─────────────┬───────────────┼──────────┬─────┴──────┐
│                    ▼             ▼               ▼          ▼            ▼
│              ┌──────────┐ ┌────────────┐ ┌─────────────┐ ┌──────┐ ┌───────────┐
│              │ Ingest + │ │ LlamaIndex │ │ Session      │ │ Sync │ │ LlamaIndex│
│              │ extract  │ │ + LanceDB  │ │ capture      │ │engine│ │ LLM       │
│              │ (Sprint 3│ │ hybrid     │ │ (mic, local  │ │(§5.5)│ │ abstraction│
│              │ tiering) │ │ vec+BM25   │ │  Whisper)    │ │      │ │ (pluggable)│
│              └──────────┘ └────────────┘ └─────────────┘ └──────┘ └───────────┘
└───────────────────────────────────────────────────────────────────┘
         │                                                    │
         ▼                                                    ▼
   Canvas (via the MCP server)                        LLM provider API
   (student's own token)                          (student's own key — §10)
```

**Why a local backend process instead of logic embedded directly in the frontend:** the RAG stack
(LanceDB, a local embedding model, Whisper) is Python-native; the UI is web technology (the
existing mockup). Rather than reimplementing ML tooling in Rust/JS or shipping a second runtime
awkwardly, Tauri's Rust shell manages a bundled Python backend as a sidecar process, started and
stopped with the app — the student never sees "Python," they see one app icon. The backend binds
to loopback (`127.0.0.1`) only; nothing about this port is reachable from outside the machine.

**Why not a plugin/library architecture instead of an HTTP boundary between frontend and backend:**
a process boundary keeps a Python crash (a bad PDF, a flaky embedding call) from taking the UI down
with it, and keeps the interface between UI and logic explicit and testable independently — the
frontend team and backend team can work against a fixed contract (§2) without blocking each other.

## 2. Component interfaces

The frontend never talks to Canvas, the vector store, or an LLM directly — everything goes through
the local backend's HTTP API. Request/response shapes, not full OpenAPI, but enough to build
against:

### `POST /courses/{course_id}/ask`
```
Request:  { "question": string, "mode": "answer" | "socratic" }
Response: { "answer": string,
            "citations": [ { "source_type": "page"|"file"|"transcript"|"notes",
                              "label": string,        // e.g. "Lecture 6 · 14:22"
                              "item_id": string } ],
            "grounded": boolean }     // false when nothing relevant was retrieved (§7)
```

### `POST /courses/{course_id}/assignments/{assignment_id}/explain`
```
Request:  {}
Response: { "breakdown": [string],           // "what's being asked", per §7.1
            "pointers": [ { "label": string, "item_id": string } ] }
```
No "draft" field exists in this contract at all — not omitted by convention, structurally absent,
so a future change can't accidentally wire a draft-generation path through this endpoint (§7.1,
§4).

### `POST /courses/{course_id}/artifacts/{type}`
`type` ∈ `mock_test | mindmap | flashcards | slides`.
```
Response: { "artifact": <type-specific structure>,
            "sources": [ { "item_id": string, "label": string } ],
            "groundedness": "n / n sources verified" }
```

### `POST /courses/{course_id}/sessions/start`
Called when the frontend detects the current time is inside a scheduled window (§9.2) and the
student confirms the prompt.
```
Response: { "session_id": string, "status": "recording" }
```
Followed by `POST /sessions/{session_id}/stop`, and the transcript/notes indexing (§9.3) happens
server-side once stopped.

### `POST /sync`
Triggered on app launch (§5.5), **asynchronously** — it must never block session-capture
recognition (§9.2). A student opening the app right as class starts needs the record prompt
immediately, not after a 20-second sync across several courses finishes. No request body; runs the
manifest diff for every selected course and returns a summary, not the full diff, since the
frontend only needs to know it happened:
```
Response: { "courses_synced": number, "items_new": number, "items_updated": number,
            "items_removed": number }
```

### `POST /courses/{course_id}/unselect`
Stops syncing and removes the course from the active list — **does not touch its data on disk.**
```
Response: { "status": "unselected" }
```
Reversible: re-selecting the same course later resumes from the existing manifest ([data-model.md](data-model.md)
§4) rather than re-ingesting everything, since already-synced items just look "unchanged" to the
diff.

### `DELETE /courses/{course_id}`
The actual destructive path, structurally separate from `unselect` above rather than one endpoint
with a dangerous flag — permanently deletes the course's LanceDB table, its manifest, and its
entire `courses/{id}/` directory, **including every session recording and note.** The frontend
should make this deliberately harder to trigger than a plain confirm dialog (e.g. typing the
course code to confirm), given recordings are stated elsewhere (§5) as unrecoverable if lost.
```
Response: { "status": "deleted" }
```

### Error responses

Every endpoint above returns errors in one shape, using HTTP status codes semantically (so the
frontend can branch on status class before parsing the body) plus a stable, machine-readable
`code` for specific UI behavior:

```
{ "error": { "code": string, "message": string, "detail"?: object } }
```

| Scenario | Status | `code` | Frontend behavior |
| --- | --- | --- | --- |
| Canvas token invalid or expired | 401 | `canvas_auth_failed` | Prompt to reconnect Canvas (§5.4) |
| Canvas unreachable or timed out | 503 | `canvas_unreachable` | Transient banner, retry |
| LLM key invalid | 401 | `llm_auth_failed` | Prompt to reconnect the LLM key |
| LLM rate-limited | 429 | `llm_rate_limited` | Transient banner, retry (`detail.retry_after`) |
| LLM out of credit | 402 | `llm_quota_exceeded` | Distinct message — "add credit," not "reconnect" |
| LLM provider unreachable | 503 | `llm_unreachable` | Transient banner, retry |
| Local model files missing or corrupted | 500 | `model_files_missing` | "Reinstall the app" — should never happen if bundled correctly, but a real failure mode for a corrupted install |
| Bad or stale course/assignment/session ID | 404 | `not_found` | Almost certainly a frontend bug — log it, generic error |
| Conflicting action (e.g. sync already running) | 409 | `sync_in_progress` | Disable the action rather than queuing it silently |

`*_auth_failed` codes are the trigger for re-authentication — credentials are validated once at
onboarding (§5.4) but tokens expire and keys get revoked afterward, and the app needs a defined
signal to prompt reconnecting rather than failing silently mid-use.

### Internal: retrieval (§5.3)
Not exposed over HTTP — this is the seam inside the backend that keeps the vector store swappable.
Rather than a hand-rolled interface, this is LlamaIndex's own `VectorStoreIndex` over a
`LanceDBVectorStore`, queried through a `CitationQueryEngine` with a `SimilarityPostprocessor` for
the groundedness cutoff — full detail and verified library references in
[rag-pipeline.md](rag-pipeline.md). Nothing above this layer (the HTTP endpoints in this section)
knows or cares that LanceDB is the concrete store.

## 3. Deployment

**Packaging.** A single Tauri `.app` bundle for macOS. The Python backend is frozen into a
standalone binary (e.g. PyInstaller) and bundled as a Tauri sidecar — the student installs one
app, never a Python environment, never `pip install` anything themselves.

**Keeping torch out of the shipped bundle is a real, verified constraint on this, not a nice-to-have.**
PyInstaller bundling torch is a confirmed, widely-reported problem (3–5GB executables, a
macOS-specific shared-library duplication bug making it worse on our exact platform) — see
[rag-pipeline.md](rag-pipeline.md) §3 for the measured comparison (874MB torch-free vs. 1.8GB
with it) and the embedding-layer decision that keeps torch confined to our own build environment,
never the shipped app.

**Model files ship bundled in the installer, not downloaded on first run.** The converted ONNX
embedding model and the CTranslate2 Whisper model are both small enough to include directly —
consistent with "self-hosted, works offline from first launch" rather than adding a hidden
first-run network dependency that would quietly undercut that claim.

**Scope: macOS only for the MVP.** Cross-platform (Windows/Linux via Tauri) is a stated future
goal, not a Sprint 4–9 commitment — see the design spec's Technology Choices (§10) for the
reasoning.

**Distribution.** Signed and notarized for Gatekeeper, per standard macOS app distribution — an
unsigned app triggering a security warning on first launch is a real adoption killer for a
self-serve, no-IT-ticket product (§2).

## 4. Security

**Credentials never touch a plaintext config file.** The Canvas token and LLM API key (§5.4) are
stored in the macOS Keychain via Tauri's keychain integration, not in `config.json` alongside
non-sensitive settings ([data-model.md](data-model.md)). This is the concrete mechanism behind
§6's "never in the repo, never transmitted" claim — Keychain entries are OS-encrypted at rest and
scoped to the app.

**The local backend port is not a security boundary that needs hardening against network attackers**
— it's loopback-only, unreachable from outside the machine — but it should still validate its own
inputs (a malformed request from a compromised frontend shouldn't crash the backend or write
outside the student's own data directory).

**Local data at rest is not separately encrypted** beyond whatever FileVault the student has
enabled system-wide. This is a real, named gap, not an oversight: full application-level encryption
of the vector store and recordings would need a passphrase/key-management story of its own, and
that's added complexity with no clear owner in the MVP. Worth revisiting if Sprint 8's
responsible-AI review surfaces it as a real risk rather than a theoretical one.

## 5. Reliability

| Failure | Behavior |
| --- | --- |
| LLM provider API is down or rate-limited | Surface a clear, specific error in the UI ("couldn't reach \[provider]") — never a silent hang, never a fallback to an ungrounded response |
| Sync fails partway through | §5.5's write-after-success ordering means the unfinished item just looks "still pending" next sync — no corruption, no special recovery path |
| Vector index file is corrupted or missing | Rebuildable from Canvas content on demand — it's a derived cache, not irreplaceable. Full course re-ingestion, same as first run |
| A recording or transcript file is corrupted | **Not recoverable** — this is original, non-reproducible data (§6), unlike the index. No mitigation beyond standard filesystem reliability exists in the MVP; worth flagging rather than pretending it's a solved problem |
| Backend sidecar process crashes | Tauri restarts it; an in-progress question fails visibly rather than hanging, an in-progress recording is the one case where a crash has real, unrecoverable cost — same caveat as above |
