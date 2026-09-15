# SSB — Student Second Brain — Design Spec

Course: 49797, Special Topics: Advanced AI for Industry and Society (Fall 2026)
Date: 2026-09-14
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
2. **Tailored to CMU.** Built against `canvas.cmu.edu` and real CMU course structure rather than a
   lowest-common-denominator LMS abstraction.
3. **Study artifacts, not just answers.** UniFlow does Q&A, transcription, and writing polish. It
   does not generate mock tests, mindmaps, or flashcards from your indexed material. That is the
   part of "second brain" that actually changes how you study.

## 2. Users

- **User**: CMU masters students, self-serve, one install per student.
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

**Deliberately deferred, in priority order:**

- **Pre-class prep brief** — before each session, generate "here's what to review" from the prior
  session's transcript plus assigned readings. Highest-value next feature; deferred only on time.
- **Assignment helper.** Deferred on principle as much as time: a tool that helps with graded work
  needs an academic-integrity stance before it needs an implementation. SSB's position is that
  grounded explanation of *course material* is categorically different from producing *submittable
  work*, and we are not shipping the second until we can enforce that line. This is the answer for
  the Sprint 8 responsible-AI review.
- **Piazza as a source.** High-value content, but no official public API — an unofficial client is
  fragile and legally murky. Named as planned, not built.
- **Writing assistant.** UniFlow parity feature, lowest marginal value for us.

## 5. Architecture

```
┌──────────────────────────────────────────────────────────────┐
│ SSB app (our frontend)                                       │
│   sidebar: SSB │ STO │ SRD │ 49797                           │
│   course home: [mock test] [mindmap] [flashcards]            │
│   ask-questions bar                                          │
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

This is a direct response to §10: we have already changed retrieval substrate once. It should
never again be a decision that puts the project at risk.

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
- **Credentials** — the Canvas token lives in the student's local environment, never in the repo,
  never transmitted to any SSB-operated service.

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

The scheduled flow from the design whiteboard:

1. SSB reads the course meeting schedule.
2. At class time, it auto-creates a `Class #N` page for that course.
3. It starts recording, transcribes, and embeds the transcript in the page.
4. An empty notes editor sits alongside the recording on the same page.
5. Transcript and notes are indexed into the student's private store, making them available to
   Q&A and artifact generation.

The point: the artifact of attending class creates itself, and immediately becomes searchable
alongside the official course material. That is the "second brain" claim in one flow.

## 10. Technology choices

| Layer | Choice | Rationale |
| --- | --- | --- |
| Vector store | Embedded, on-disk, per-student (LanceDB or equivalent) | Hybrid BM25+vector, zero server processes, one directory per student maps exactly to §5.1 |
| Canvas access | Canvas MCP server | Already working; live reads for personal data |
| Transcription | Whisper, local | Open-source thesis; recordings never leave the machine. UniFlow uses hosted Deepgram |
| LLM | Pluggable, default Claude | Swappable; local models possible for full self-hosting |
| Web search | MCP, explicitly labeled | Never silently blended with course-grounded answers |

### 10.1 Why not Onyx — the Sprint 3 finding

Sprints 1–3 targeted self-hosted [Onyx](https://github.com/onyx-dot-app/onyx). We built a real
integration: a 1,068-line native `CanvasConnector` implementing Onyx's
`CheckpointedConnectorWithPermSync` and `SlimConnectorWithPermSync` interfaces — checkpointing,
retry, pagination, HTML parsing, and document conversion for courses, pages, assignments, and
announcements — running live in an Onyx v4.7.3 Standard deployment.

It ran. Against a live CMU course it indexed courses, pages, assignments, and announcements — but
only after three separate fixes to survive a student-scoped token: 404s on disabled Pages tabs
skipping the entire course, per-stage 403s marking the whole connector INVALID, and privileged
assignment includes (`assignment_visibility`, `overrides`) that students cannot request. It never
reached modules or files, **which is where most CMU course content actually lives.** Getting there
needed a larger connector change we chose not to make.

We are moving off it, for three findings:

1. **The permission model requires a commercially-licensed tier.** Onyx CE is MIT, but permission
   sync resolves through `fetch_versioned_implementation` to an enterprise implementation under a
   separate commercial license. Our connector's entire ACL design — `ExternalAccess`, course /
   section / group permission contexts — needs that tier. **An open-source product cannot have a
   permission model that requires a commercial license.** This is a contradiction, not a tradeoff.
2. **Per-student isolation runs against Onyx's architecture.** Onyx is designed as one shared
   corpus with connectors, users, and document sets. Per-student isolation means either one Onyx
   instance per student — 11 containers each — or document sets with no enforcement, which is the
   filter-bug leak §5.1 exists to avoid.
3. **The deployment shape is wrong for the user.** Onyx Standard runs 11 containers (OpenSearch,
   Postgres, Redis, MinIO, two model servers, nginx, code-interpreter, web, api, background) and
   wants 10–16GB of Docker RAM. Our competitor is a desktop app. "Install Docker and run eleven
   containers" is not a student onboarding flow.

Two things Onyx did **not** solve, which is why moving costs less than it appears: it does not
fix image-heavy PDF ingestion (§11), the risk we named as largest; and we had already decided to
build our own frontend, fetch personal data live rather than index it, and keep transcripts
private — three decisions that independently discard most of what Onyx was providing. What
remained was chunk / embed / retrieve, the most commoditized layer in the stack.

**Sprint 3 decision: MODIFY.** Retrieval-augmented generation over real Canvas content remains the
approach and is validated. The substrate changes. The Canvas API work in the connector — endpoints,
pagination, HTML parsing, document conversion — ports to the new ingestion path; the Onyx interface
scaffolding is dropped.

## 11. Risks

- **Image-heavy PDF ingestion.** Observed directly: `read_course_file` on a real course PDF
  returned base64 bytes, not text, and the underlying content is images with text overlay. Slide
  decks are the single most valuable content type and the hardest to ingest. Needs a VLM/OCR pass.
  **Unchanged by the Onyx decision — no platform solves this for us.** Largest open risk.
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
| 3 | Sep 15 | Feasibility + baseline; Onyx finding; **Modify** decision (§10.1) |
| 4 | Sep 22 | System architecture and implementation plan |
| 5 | Sep 29 | Core prototype: ingestion + retrieval + grounded cited Q&A |
| 6 | Oct 6 | End-to-end alpha: + session capture, + study artifacts |
| 7 | Oct 20 | User/stakeholder and impact validation |
| 8 | Oct 27 | Robustness and responsible AI (§4 integrity stance, §6 privacy model) |
| 9 | Nov 17 | Beta and independent testing |
| Final | Dec 1 | Product, impact, and defense |

**Pilot courses:** 49797 (Advanced AI for Industry and Society) as primary — already indexed, and
the professor can see it working on their own material. 18654 (Software Testing and Operations) as
the second course, to prove the multi-course sidebar on genuinely different content.
