# SSB — Student Second Brain — Design Spec

Course: 49797, Special Topics: Advanced AI for Industry and Society (Fall 2026)
Date: 2026-09-15
Supersedes: `2026-09-11-canvas-ai-tutor-design.md`

## 1. Thesis

**SSB (Student Second Brain) is the open-source alternative to [UniFlow Study](https://www.uniflowstudy.com/).**

One app per student that ingests their real course material, captures their lectures, answers
questions with citations back to the source, and generates the study artifacts they would
otherwise build by hand — mock tests, mindmaps, slides, flashcards.

Three differentiators:

1. **Open source.** Self-hostable, no subscription. UniFlow charges $12.80–$39.20/month and meters
   AI conversations (30/month on free). More importantly: the student's index, recordings, and
   notes live on hardware the student controls.
2. **Tailored to Canvas.** Built against real Canvas structure — modules, pages, assignments,
   files — rather than a lowest-common-denominator LMS abstraction. Validated first against
   `canvas.cmu.edu` as the pilot instance, but the target user is any Canvas-using student, not a
   CMU-only product.
3. **Study artifacts, not just answers.** UniFlow does Q&A, transcription, and writing polish. It
   does not generate mock tests, mindmaps, or flashcards from your indexed material. That is the
   part of "second brain" that actually changes how you study.

## 2. Users

- **User**: any student whose courses run on Canvas, self-serve, one install per student. CMU is
  the pilot install base (§13), not a scope limit — nothing in the architecture is CMU-specific
  beyond the pilot Canvas instance used to validate it.
- **Customer**: the same students — no institutional gatekeeper, no professor approval, no IT
  ticket. This is a deliberate go-to-market choice, not just an MVP shortcut.
- **Beneficiary**: students directly. Instructors indirectly, via fewer repeated questions.

## 3. Competitive position

| | UniFlow Study | SSB |
| --- | --- | --- |
| License / cost | Proprietary, $0–$39.20/mo, metered | Open source, self-hosted, unmetered |
| Data location | Vendor cloud | Student's own machine |
| Grounded cited Q&A | Yes ("UniMind") | Yes |
| LMS sync | Canvas, Blackboard, Moodle | Canvas (CMU-first) |
| Lecture transcription | Yes (Deepgram, bilingual) | Yes (Whisper, local) |
| Mock tests / mindmaps / flashcards | No | **Yes** |
| Session notes pages | Partial (editor) | **Yes, auto-created on class schedule** |
| Writing assistant | Yes | Deferred |
| Personal data in a vector store | Unknown | **Never** — fetched live, never indexed |

The honest read: UniFlow is broader today (Blackboard/Moodle, bilingual transcription, writing
assistant). SSB wins on ownership, cost, and the generate-study-material axis. We do not claim
parity and should not.

## 4. Scope

**MVP (Sprints 4–6):**

1. **Grounded Q&A** over the student's indexed course material. Answer-first with citations;
   Socratic mode as a toggle.
2. **Lecture capture** — transcription plus an auto-created per-session page with the recording
   and a notes editor embedded.
3. **Study artifacts** — mock test, mindmap, slides, flashcards, generated from indexed material
   with citations.
4. **Assignment explainer** — on request, breaks down what a specific assignment is asking and
   points to the indexed lecture and reading material it draws on, cited the same way Q&A is. It
   does not draft answers, code, or any submittable text — see §7.1 for exactly where that line
   sits, and why it's distinct from the assignment *helper* below, which stays deferred.

**Deliberately deferred, in priority order:**

- **Pre-class prep brief** — before each session, generate "here's what to review" from the prior
  session's transcript plus assigned readings. Highest-value next feature; deferred only on time.
- **Assignment helper** — anything that drafts, completes, or substantially generates submittable
  work: code, written answers, problem-set solutions. This is still deferred on principle, not
  time: SSB explains the *prompt* and the *material* (§7.1), and does not produce the *submission*.
  That line, and how we intend to enforce it technically rather than just by instruction to the
  model, is the answer for the Sprint 8 responsible-AI review.
- **Piazza as a source.** High-value content, but no official public API — an unofficial client is
  fragile and legally murky. Named as planned, not built.
- **Writing assistant.** UniFlow parity feature, lowest marginal value for us.

## 5. Architecture

```
┌──────────────────────────────────────────────────────────────┐
│ SSB app (our frontend)                                       │
│   onboarding: connect Canvas + LLM keys → select courses     │
│               → index (assignments, modules, files)          │
│   sidebar: courses │ sessions                                │
│   course home: chat column (Q&A)  │  next assignment,        │
│                                    │  study artifacts,        │
│                                    │  recent sessions          │
│   assignment page: prompt → [explain this assignment]        │
│   session pages: Class #N → [recording] + [notes]            │
└─────────────────────────────┬────────────────────────────────┘
                              │ HTTP / JSON
┌─────────────────────────────▼────────────────────────────────┐
│ SSB backend                                                  │
│   ingest     Canvas → parse → chunk → embed                  │
│   retrieve   Retriever interface (hybrid BM25 + vector)      │
│   answer     answer-first + citations │ Socratic toggle      │
│   artifacts  mock test / mindmap / slides / flashcards       │
│   sessions   scheduler: class time → page + start recording  │
│   live       Canvas personal data — passthrough, never indexed│
└──┬────────────────┬──────────────┬──────────────┬────────────┘
   │                │              │              │
┌──▼─────────────┐ ┌▼───────────┐ ┌▼───────────┐ ┌▼───────────┐
│ Per-student    │ │ Canvas MCP │ │ Whisper    │ │ LLM        │
│ vector store   │ │ live reads │ │ local      │ │ pluggable  │
│ ~/.ssb/<id>/   │ │ deadlines  │ │ transcribe │ │ default    │
│   docs/        │ │ grades     │ └────────────┘ │ Claude     │
│   recordings/  │ │ submissions│                └────────────┘
│   notes/       │ └────────────┘  + web search MCP
└────────────────┘
```

### 5.1 One index per student

Every student gets their own on-disk index containing their course documents, their recordings,
and their notes. Nothing is shared between students.

This is **physical** isolation — one directory per student — not a filter flag on a shared
corpus. A query-filter bug in a shared store is a cross-student data leak; a missing directory is
an empty result. For a system holding lecture recordings and personal academic data, that
asymmetry is worth paying for.

**The cost, stated plainly:** the same slide deck is embedded once per student, and the class gets
no network effect from each other's recordings. We accept both. Storage is cheap relative to the
blast radius of a leak, and the recording-consent story (§6) is only defensible because nothing is
shared.

### 5.2 Personal Canvas data is never indexed

Deadlines, grades, and submission status are fetched **live through the Canvas MCP server using
the student's own token, per request**. They never enter a vector store.

Two reasons: freshness (a grade indexed last Tuesday is wrong today) and blast radius (grades in
an embedding store are a liability with no corresponding benefit).

### 5.3 Retrieval behind an interface

All retrieval sits behind a single `Retriever` interface — `index(documents)` and
`search(query, k) -> list[Chunk]` with source metadata. The concrete store is an implementation
detail.

This keeps the concrete retrieval store swappable by design — the choice of vector store or
search backend should never become a decision that puts the project at risk partway through the
semester.

### 5.4 Onboarding and first-run setup

First run is a four-step flow, not a settings page buried after install: connect credentials,
pick courses, watch them index, land in the app already populated with real content instead of an
empty shell.

1. **Connect accounts.** The student enters their Canvas API token and an LLM API key. Both stay
   on the student's machine — read once, used to talk to Canvas and the model provider directly,
   never transmitted to any SSB-operated service (§6).
2. **Select courses.** SSB fetches the student's enrolled courses from Canvas and lists them for
   selection — not every enrolled course needs indexing on day one. Each selected course also gets
   a weekly meeting schedule set here (day, time, session type), the basis for session capture
   (§9.1) — editable later from Settings.
3. **Index.** For each selected course, SSB ingests assignments, modules, and files (the
   image-heavy-PDF risk noted in §11 lives here) with visible per-course, per-content-type
   progress. This is the one-time cost; after it completes, everything is local.
4. **Land in the app**, populated with the student's own courses rather than an empty state.

The point of making this a first-class flow rather than a wizard to get through: a screen showing
indexing progress *is* the "your machine, your index" claim (§5.1) made visible, the first time a
student sees the product.

### 5.5 Keeping the index fresh

Onboarding (§5.4) is a one-time cost. What happens after — when a professor edits a page, posts a
new assignment, or uploads a slide deck mid-semester — is a separate, ongoing problem: the index
has to stay current without turning into a background service.

**Personal data stays out of this entirely.** Grades, deadlines, and submission status are already
live-only per §5.2 and never touch the index — nothing about sync applies to them.

**Trigger: sync on app launch, not a wall-clock schedule.** Canvas's push/webhook mechanisms are
institution-admin-level, not available to a plain student-scoped token — the same access ceiling
Sprint 3 hit with `list_course_files`. Polling is therefore the only realistic option, and running
it as a background daemon (a launch agent keeping the app "alive" to fire on a schedule) is real
engineering complexity for a desktop app that has no other reason to run as a service. Syncing
whenever the app opens is cheaper, needs no OS-level scheduling, and matches how a study app
actually gets used — opened when needed, not run passively in the background. A lightweight
periodic re-check while the app stays open (every few hours) covers long sessions.

**Mechanism: a full ID-and-timestamp diff, not a content re-pull.** Every sync, SSB fetches the
current listing (ID + `updated_at`) for each content type from Canvas — cheap, metadata only, a
handful of API calls even across several courses — and diffs it against a local sync manifest, one
row per ingested item:

| Field | Purpose |
| --- | --- |
| `canvas_item_id` | Stable ID from Canvas (page / assignment / announcement / file) |
| `item_type` | page / assignment / announcement / file |
| `canvas_updated_at` | Canvas's own timestamp, last time SSB saw it |
| `content_hash` | Hash of the *extracted* text (post plain-text/OCR/vision pipeline, §10.1), not the raw bytes |
| `chunk_ids` | Which vector-store chunks came from this item, so they can be deleted precisely on update or removal |

The diff sorts every item into one of four buckets:

- **New** (remote ID not in the manifest) — fetch, extract, chunk, embed, insert, write the
  manifest row.
- **Changed** (`remote updated_at` newer than the manifest's) — re-fetch and re-extract, then check
  the content hash before doing anything expensive: unchanged hash means a metadata-only touch
  (rename, permission change) — just bump the stored timestamp. A real hash difference means
  delete the item's old chunks, embed the new content, update the manifest.
- **Deleted** (manifest ID absent from the current remote listing) — delete its chunks, drop the
  manifest row. Pulling the *complete* ID set every sync, rather than asking Canvas "what changed
  since X," is what makes this fall out for free: an unpublish or removal doesn't register as a
  "change" to a timestamp-only query, it just disappears from the listing.
- **Unchanged** (same ID, same timestamp) — skip; no content fetch at all.

**Two efficiency details worth keeping:** hash the raw file bytes as a fast pre-check before
extraction (identical bytes skip extraction entirely) — extraction and embedding are the expensive
steps, not the metadata diff. And write a manifest row only after its vector-store write succeeds,
so a sync that crashes partway through leaves the unfinished item looking "still new" next run,
with no separate crash-recovery path needed.

Session recordings, transcripts, and notes sit outside this mechanism entirely — they aren't from
Canvas, so there's nothing to diff against. They're re-embedded on save/edit using the same
hash-skip-if-unchanged idea, with SSB itself as the source of truth.

## 6. Data and privacy model

- **Course documents** — pulled from Canvas with the student's own token. Only material that
  student already has access to.
- **Recordings and transcripts** — **always private to the student who recorded them.** Never
  shared, never published to a common index, no opt-in sharing path in the MVP. Lecture recording
  touches instructor and classmate consent and varies by jurisdiction; the only stance we can
  defend without a consent mechanism we have not built is "your recording, your machine, nobody
  else's."
- **Notes** — private, same tier.
- **Personal academic data** — never persisted by SSB at all (§5.2).
- **Credentials** — the Canvas token and the student's LLM API key, both entered once during
  onboarding (§5.4), live in the student's local environment, never in the repo, never transmitted
  to any SSB-operated service.

## 7. Tutor behavior

**Default: answer-first with citations.** A direct, useful answer, with every factual claim
traceable to a specific indexed page, file, or transcript segment. This matches what students
actually want under time pressure and matches the UniFlow behavior we are positioned against.

**Socratic mode is a toggle**, not the default — guiding questions first, answer on request. It
stays in the product because it is genuinely better for exam prep, and because it is the feature
the professor has seen since Sprint 1. Making it opt-in is the change.

**Grounding is non-negotiable in both modes.** If indexed material does not support an answer, SSB
says so rather than falling back to open-domain knowledge. Optional web search is a *separate,
visibly-labeled* path — never silently blended into a course-grounded answer.

### 7.1 Assignment explainer

A narrow, principled carve-out from the "assignment helper" deferral in §4: SSB will explain what
an assignment is asking, grounded in the student's own course material, and will not draft any
part of the submission.

**What it does.** From the course's assignment list, the student opens the next-due assignment —
title, due date, weight, and the prompt as pulled from Canvas. An "Explain this assignment"
action, on request, returns two things:

1. **What's being asked** — the prompt broken into its actual sub-requirements, in plain language.
   This is reading comprehension of the assignment text itself, not course content.
2. **Where to start** — pointers into the student's own indexed material (lecture timestamps,
   readings) relevant to the assignment, cited the same way Q&A citations work.

**What it does not do.** It does not produce code, written answers, problem-set solutions, or any
text a student could submit as their own work. There is no "generate a draft" action, and none is
planned. The output is visibly labeled as an explanation, the same pattern used for web search
above — the student always knows which kind of response they're looking at.

**Why this is different from the deferred assignment helper.** Breaking down what a prompt is
asking and citing relevant lecture material is grounded explanation of the student's own course
content — the same category of behavior as Q&A above, just scoped to one assignment's prompt
instead of an open question. It carries no more academic-integrity risk than a TA pointing a
student back to the right lecture. Producing any part of the submission itself is a different act
entirely, and stays deferred until SSB can enforce that boundary technically, not just by
instruction to the model.

## 8. Study artifacts

Generated from indexed material, each with citations back to source:

- **Mock test** — questions with answers, each traceable to the material it tests.
- **Mindmap** — concept graph across a module or course.
- **Slides** — condensed deck from a topic.
- **Flashcards** — spaced-repetition-ready pairs.

**The quality bar is different from Q&A and needs its own metric.** A wrong answer is visibly
wrong and a student can push back. A mock test with three plausible-but-hallucinated questions is
*worse than no mock test*, because the student studies the wrong thing and does not find out until
the exam. Artifact groundedness is therefore a first-class metric (§11), not a sub-case of answer
groundedness.

## 9. Session capture

### 9.1 Where the schedule comes from

There's no Canvas API access to a course's meeting schedule — checked directly, no calendar
endpoint is exposed to a student-scoped token, and a real pilot course's Syllabus tab turned out to
be a link to a PDF, not structured text (the same tiered-extraction problem as §10.1, with no
guarantee the PDF states meeting times cleanly even then). Auto-detection can't be the primary
path, because there's nothing reliable to detect it from.

**Manual entry is the primary path.** During onboarding (§5.4), selecting a course includes setting
its weekly meeting schedule — day, start/end time, and a session-type label for courses with more
than one meeting pattern (lecture vs. recitation, most commonly). SSB attempts a best-effort
pre-fill from syllabus text where extraction finds something schedule-shaped, always shown as an
unconfirmed guess the student reviews, never as a confident answer. The schedule stays editable
afterward from Settings — a professor moving one week's class, a added recitation, a schedule typo
caught later.

### 9.2 Triggering a session

No background service watches the clock for this. §5.5 accepted eventually-consistent freshness
for content sync because staleness is recoverable by the next app launch; a missed recording is
not recoverable at all — there's no "catch up later" for a lecture that already happened. That
asymmetry would argue *for* background presence here even though §5.5 argued against it for
sync, but for now the simpler path stands: **when the student opens the app and the current time
falls inside a scheduled window for one of their courses, SSB recognizes the window and prompts to
start the session** — page, recording, and notes editor together — rather than silently
auto-starting. Recording is consent-sensitive (§6), so starting it is an explicit action, not an
ambient one, and it only happens at all if the student opens the app during class.

**Known limitation:** a class the student doesn't open the app for during its scheduled window
isn't captured, with no way to recover it after the fact. A scheduled-wake background process is a
plausible later upgrade if this turns out to matter in practice — not committed for the MVP.

### 9.3 The capture flow

1. The student opens the app inside a scheduled window; SSB prompts to start the session.
2. On confirmation, SSB creates a `Class #N` page for that course, starts recording, and
   transcribes locally.
3. An empty notes editor sits alongside the recording on the same page.
4. Transcript and notes are indexed into the student's private store, making them available to
   Q&A and artifact generation.

The point: the artifact of attending class creates itself with one confirmation, and immediately
becomes searchable alongside the official course material. That is the "second brain" claim in one
flow.

## 10. Technology choices

| Layer | Choice | Rationale |
| --- | --- | --- |
| Vector store | Embedded, on-disk, per-student (LanceDB or equivalent) | Hybrid BM25+vector, zero server processes, one directory per student maps exactly to §5.1 |
| Canvas access | Canvas MCP server | Already working; live reads for personal data |
| Transcription | Whisper, local | Open-source thesis; recordings never leave the machine. UniFlow uses hosted Deepgram |
| LLM | Pluggable, default Claude | Swappable; local models possible for full self-hosting |
| Web search | MCP, explicitly labeled | Never silently blended with course-grounded answers |

### 10.1 PDF and slide ingestion — the Sprint 3 finding

Image-heavy PDFs and slide decks are the single most valuable content type in most courses and the
hardest to ingest reliably. Sprint 3's proof of concept pulled two real files from a live course —
an 11-page PDF exported from a tutorial-style slide deck, and a 15-slide native PowerPoint deck —
and tested three extraction tiers against each: plain-text extraction, OCR, and a direct
vision-model read.

**Native formats are close to a non-issue.** The PPTX extracted well from plain text alone —
47–664 real text characters per slide across 15 slides, with only 4 slides containing any embedded
picture at all.

**Exported, screenshot-heavy PDFs are the real case.** Plain-text extraction on the PDF returned
6–300 characters per page (1,614 total across 11 pages) — mostly just slide titles. Every page had
1–3 embedded screenshots, and that's where the actual instructional content lived. OCR on full
rasterized pages recovered roughly 3x more text (4,980 characters total) in 4.6 seconds for all 11
pages — fast, free, a real improvement — but noisy, mixing genuine content with UI-chrome garbage.
A direct vision-model pass on one representative page produced a clean, structured read that
correctly identified a red box around one option as a deliberate visual callout marking the
correct answer — the actual instructional content of the slide, and something structurally
invisible to both plain-text extraction and OCR.

**Decision: extraction should be tiered, not uniform.** Plain-text extraction first (free,
instant, sufficient for native formats); a cheap density heuristic (characters extracted per page)
flags pages likely to be image-heavy; flagged pages get OCR by default, with a vision-model pass
reserved for pages where OCR quality is still poor or where structural understanding (diagrams,
annotated screenshots) actually matters. Full method and results: [Sprint 3](sprints/sprint-03.md).

This is one PDF and one deck from one course — a real result, not a comprehensive benchmark. The
density heuristic's threshold needs tuning against more course material before Sprint 5, and the
vision-tier's cost/latency at full-course scale is not yet measured.

## 11. Risks

- **Image-heavy PDF ingestion.** Partially de-risked by the Sprint 3 finding (§10.1): a tiered
  plain-text → OCR → vision-model strategy recovers real content, but the density-heuristic
  threshold and the vision-tier's cost at full-course scale are still untuned. No longer the
  largest *unknown* risk, but still the largest *unresolved* one going into Sprint 5.
- **Artifact groundedness.** A hallucinated mock test actively harms the student (§8).
- **Per-student storage cost.** Duplicate embeddings scale linearly with enrollment. Acceptable at
  pilot scale; a real constraint on any institutional deployment.
- **Recording consent.** Mitigated by always-private (§6), not eliminated. An instructor may still
  object to being recorded at all.
- **Rebuild cost lands in Sprint 5.** Ingestion, hybrid retrieval, and citation plumbing are
  roughly 1–2 weeks. Mitigated by the `Retriever` interface (§5.3) and by the Canvas work porting
  over.
- **Scope.** Three MVP pillars in three sprints is aggressive. Q&A is the pillar that ships even
  if the others slip.

## 12. Success metrics

**Technical**

- **Citation groundedness rate** — % of answers where the cited source actually supports the
  claim, hand-graded on a fixed question set.
- **Retrieval precision@k** — against known expected sources.
- **Artifact groundedness** — % of generated mock-test questions answerable from their cited
  source. Graded separately from answer groundedness (§8).
- **Transcription WER** — on a real recorded lecture, not a clean benchmark clip.

**User / impact**

- Return usage during exam weeks.
- Pre/post self-reported confidence on the material.
- Artifacts actually used to study, versus generated and abandoned — the honest test of §8.

## 13. Roadmap

| Sprint | Due | Deliverable |
| --- | --- | --- |
| [1](sprints/sprint-01.md) | Sep 1 | Individual problem discovery and solution proposal — **complete** |
| [2](sprints/sprint-02.md) | Sep 8 | Problem validation, requirements, MVP scope — **complete** |
| [3](sprints/sprint-03.md) | Sep 15 | Feasibility + baseline — **complete** |
| [4](sprints/sprint-04.md) | Sep 22 | System architecture and implementation plan |
| [5](sprints/sprint-05.md) | Sep 29 | Core prototype: ingestion + retrieval + grounded cited Q&A |
| [6](sprints/sprint-06.md) | Oct 6 | End-to-end alpha: + session capture, + study artifacts |
| [7](sprints/sprint-07.md) | Oct 20 | User/stakeholder and impact validation |
| [8](sprints/sprint-08.md) | Oct 27 | Robustness and responsible AI (§4 integrity stance, §6 privacy model) |
| [9](sprints/sprint-09.md) | Nov 17 | Beta and independent testing |
| [Final](sprints/final.md) | Dec 1 | Product, impact, and defense |

**Pilot courses:** 49797 (Advanced AI for Industry and Society) as primary — already indexed, and
the professor can see it working on their own material. 18654 (Software Testing and Operations) as
the second course, to prove the multi-course sidebar on genuinely different content.
