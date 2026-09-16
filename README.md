# SSB — Student Second Brain

**The open-source alternative to [UniFlow Study](https://www.uniflowstudy.com/).**

One app per student that ingests your real course material, captures your lectures, answers
questions with citations back to the source, and generates the study material you'd otherwise
build by hand — mock tests, mindmaps, slides, flashcards.

Your index, your recordings, your notes, on your machine.

> **Status: early development.** Sprint 5 (core prototype) is underway — the Tauri app shell,
> Python sidecar, Keychain-backed credential storage, and Canvas integration are working
> end-to-end against real data. RAG (ingestion, embeddings, retrieval) hasn't started yet; see
> [the implementation plan](docs/architecture/implementation-plan.md) for exactly what's done.
> There is no installable build yet.

---

## Why

Every semester the same material is spread across a syllabus PDF, forty slide decks, a dozen
assignment pages, and whatever you managed to write down in class. The tooling that helps with
this is proprietary, metered, and keeps your lecture recordings on someone else's servers.

SSB is the version you can read, run, and own.

## What it does

**Ask questions about your actual courses.** Grounded answers with citations to the specific page,
file, or lecture moment they came from. If your material doesn't support an answer, SSB says so
instead of guessing. Answer-first by default; Socratic mode is a toggle for when you're studying
rather than hunting.

**Capture your lectures.** Open SSB during class and it recognizes you're in a scheduled session,
creates a page for it, starts recording, transcribes locally, and puts a notes editor next to the
transcript. Both get indexed, so this week's lecture is searchable alongside the official course
material.

**Generate study material.** Mock tests, mindmaps, slides, and flashcards built from what's
actually in your courses — each traceable to its source.

**Explain your assignments.** Breaks down what a prompt is actually asking and points to the
lecture and reading material it draws on — never drafts the answer itself. See
[§7.1 of the design spec](docs/specs/2026-09-14-ssb-design.md) for exactly where that
line sits.

## How it compares

| | UniFlow Study | SSB |
| --- | --- | --- |
| License / cost | Proprietary, $0–$39.20/mo, metered conversations | Open source, self-hosted, unmetered |
| Where your data lives | Vendor cloud | Your machine |
| Grounded cited Q&A | Yes | Yes |
| LMS sync | Canvas, Blackboard, Moodle | Canvas (CMU-first) |
| Lecture transcription | Yes — Deepgram, hosted, bilingual | Yes — Whisper, local |
| Mock tests / mindmaps / flashcards | No | **Yes** |
| Auto session notes pages | Partial | **Yes, on your class schedule** |
| Writing assistant | Yes | Not yet |
| Grades & deadlines in a vector store | Unknown | **Never** — fetched live, never indexed |

UniFlow is broader today: more LMS integrations, bilingual transcription, a writing assistant. SSB
wins on ownership, cost, and generating study material rather than just answering questions. We're
not claiming parity.

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│ SSB app                                                      │
│   onboarding: connect Canvas + LLM keys → select courses     │
│               → index (assignments, modules, files)          │
│   course sidebar · course home: chat (Q&A) + assignment,     │
│                     study artifacts, recent sessions          │
│   assignment page: prompt → [explain this assignment]        │
│   session pages: Class #N → [recording] + [notes]            │
└─────────────────────────────┬────────────────────────────────┘
┌─────────────────────────────▼────────────────────────────────┐
│ SSB backend                                                  │
│   ingest · retrieve · answer · artifacts · sessions · live   │
└──┬────────────────┬──────────────┬──────────────┬────────────┘
┌──▼─────────────┐ ┌▼───────────┐ ┌▼───────────┐ ┌▼───────────┐
│ Per-student    │ │ Canvas API │ │ Whisper    │ │ LLM        │
│ vector store   │ │ live reads │ │ local      │ │ pluggable  │
│ ~/.ssb/<id>/   │ │ deadlines  │ │ transcribe │ │ default    │
│  docs/         │ │ grades     │ └────────────┘ │ Claude     │
│  recordings/   │ │ submissions│                └────────────┘
│  notes/        │ └────────────┘  + web search MCP
└────────────────┘
```

Two decisions shape everything else:

**One index per student — physically, not by filter.** Your course documents, recordings, and
notes live in your own on-disk index. Nothing is shared between students. A query-filter bug in a
shared store leaks other people's data; a missing directory just returns nothing. For a system
holding lecture recordings, that asymmetry is worth the duplicated storage.

**Grades and deadlines are never indexed.** They're read live from Canvas with your own token, per
request. Always current, and never sitting in an embedding store.

## Project context

Built as the group project for **49797 — Special Topics: Advanced AI for Industry and Society**
(CMU-SV, Fall 2026), on a nine-sprint cadence ending December 1.

| Sprint | Due | Deliverable |
| --- | --- | --- |
| [1](docs/sprints/sprint-01.md) | Sep 1 | Individual problem discovery and solution proposal — **complete** |
| [2](docs/sprints/sprint-02.md) | Sep 8 | Problem validation, requirements, MVP scope — **complete** |
| [3](docs/sprints/sprint-03.md) | Sep 15 | Feasibility and baseline — **complete** |
| [4](docs/sprints/sprint-04.md) | Sep 22 | System architecture and implementation plan |
| [5](docs/sprints/sprint-05.md) | Sep 29 | Core prototype: ingestion, retrieval, grounded Q&A |
| [6](docs/sprints/sprint-06.md) | Oct 6 | End-to-end alpha: session capture, study artifacts |
| [7](docs/sprints/sprint-07.md) | Oct 20 | User and impact validation |
| [8](docs/sprints/sprint-08.md) | Oct 27 | Robustness and responsible AI |
| [9](docs/sprints/sprint-09.md) | Nov 17 | Beta and independent testing |
| [Final](docs/sprints/final.md) | Dec 1 | Product, impact, and defense |

Pilot courses: 49797 (primary) and 18654 Software Testing and Operations.

## Responsible AI

**Explains assignments, never drafts them.** SSB will break down what an assignment is asking and
point to the course material it draws on — grounded explanation, the same category of behavior as
Q&A. It will not produce code, written answers, or any part of a submission, and no such feature
is planned; that line is deferred on principle, not just on time, until it can be enforced
technically rather than by instruction to the model alone. See §7.1 of the design spec.

**Recordings stay private.** Always, with no sharing path. Recording a lecture involves your
instructor and your classmates, and private-by-default is the only stance defensible without a
consent mechanism we haven't built.

**Web search is labeled.** When SSB goes outside your course material, it says so. It never
silently blends outside knowledge into a course-grounded answer.

## Documentation

- [Design spec](docs/specs/2026-09-14-ssb-design.md) — architecture, scope, privacy
  model, risks, metrics
- [Architecture overview](docs/architecture/overview.md) — system diagram, HTTP API contract,
  deployment and reliability
- [Canvas integration](docs/architecture/canvas-integration.md) — real endpoints, access
  restrictions found by testing, sync mapping
- [Data model](docs/architecture/data-model.md) — on-disk layout, sync manifest schema
- [RAG pipeline](docs/architecture/rag-pipeline.md) — ingestion, embedding, retrieval, generation
- [Implementation plan](docs/architecture/implementation-plan.md) — the sequenced build order,
  a concrete test per step, and what's actually verified so far

## License

TBD — will be an OSI-approved open-source license before first release. "Open source" is the
product's central claim, so this gets settled, not left dangling.
