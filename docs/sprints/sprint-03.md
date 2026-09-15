# Sprint 3 — Technical Feasibility and Baseline

**Type:** Team · **Due:** 2026-09-15 · **Points:** 100 · **Status:** Submitted

## Purpose

Test the project's highest-risk assumptions before committing substantial implementation effort.

## Requirements

| Requirement | What Must Be Demonstrated | Weight |
| --- | --- | --- |
| Technical and Data Feasibility | Identify the most important technical risks; assess required data, APIs, models, infrastructure, tools, hardware, access restrictions, and dependencies | 35% |
| Baseline and Feasibility Prototype | Establish an appropriate baseline and implement a reproducible proof of concept testing at least one critical technical assumption using real or representative data | 45% |
| Findings and Project Decision | Analyze results and limitations; make an evidence-based Proceed, Modify, or Pivot decision with resulting changes to scope or technical direction | 20% |

## Deliverable

3–4 page feasibility report plus working baseline/proof of concept submitted to the project
repository.

---

## 1. Technical and data feasibility

### Highest-risk assumptions

Against the Must Have requirements validated in [Sprint 2](sprint-02.md) (FR1–FR8), the risks that
actually threaten the project — not just anything that could go wrong — are:

1. **Canvas ingestion depth (FR2).** Can a student-scoped token actually reach everything a
   student needs indexed — pages, assignments, announcements, modules, files — or does Canvas's
   permission model block parts of it? This is the risk this sprint's prototype was built to test.
2. **Retrieval quality over real course content (FR3, FR4).** Does RAG over real, messy Canvas
   content produce answers a student would actually trust cited?
3. **Per-student isolation without a heavy platform (FR6, NFR4).** Can the index be physically
   isolated per student and still run on a student's own machine, without adopting a multi-tenant
   platform built for a shared corpus?
4. **Credential handling across providers (FR1).** Lower technical risk, but a real dependency
   surface: a Canvas token and a pluggable LLM API key, each with its own auth format, stored and
   used locally.
5. **The assignment-explainer's explain-vs-draft boundary (FR8).** Can the model reliably explain
   a prompt and cite material without drifting into drafting an answer? This is a *behavioral*
   risk distinct from retrieval quality — **not tested by this sprint's prototype**, which
   validated retrieval, not generation behavior. Carried forward as an open risk into Sprint 5.
6. **Image-heavy PDF ingestion.** Slide decks are the single most valuable content type in most
   courses and the hardest to ingest. Observed directly this sprint: `read_course_file` on a real
   course PDF returned base64 bytes, not text — the underlying content is images with text
   overlay, needing a VLM/OCR pass no platform choice solves for free.

### Data, APIs, models, infrastructure, tools, and access restrictions

| Dependency | Role | Access restriction found |
| --- | --- | --- |
| Canvas REST API | Source of all course content, via the student's own token | Student-scoped tokens 403 on privileged assignment fields (`assignment_visibility`, `overrides`) and 404 on disabled Pages tabs — see §2 |
| Onyx (self-hosted RAG platform) | Tested as the retrieval substrate | Permission sync resolves to a commercially-licensed tier; 11-container deployment (OpenSearch, Postgres, Redis, MinIO, two model servers, etc.), 10–16GB Docker RAM — see §3 |
| Whisper (local transcription) | Planned for lecture capture (FR5) | Not yet built or tested — a Sprint 5/6 dependency, not validated by this sprint |
| LLM (pluggable, per FR1) | Answering, explaining, generating | "Pluggable" needs testing against at least two real providers, not just a theoretical interface |
| Student hardware | Where the whole system must run | Directly ruled out Onyx's footprint — see §3 |

## 2. Baseline and feasibility prototype

Built a real proof of concept against self-hosted [Onyx](https://github.com/onyx-dot-app/onyx): a
1,068-line native `CanvasConnector` implementing Onyx's `CheckpointedConnectorWithPermSync` and
`SlimConnectorWithPermSync` interfaces — checkpointing, retry, pagination, HTML parsing, and
document conversion — running in a live Onyx v4.7.3 Standard deployment against a real course,
49797, on `canvas.cmu.edu` (the pilot Canvas instance used to validate the product — see [Sprint
1](sprint-01.md)'s user definition, not a scope limit).

**It ran.** Against the live course it indexed courses, pages, assignments, and announcements —
real data, not a synthetic fixture — but only after three separate fixes to survive a
student-scoped token:

1. 404s on disabled Pages tabs were skipping the entire course.
2. Per-stage 403s were marking the whole connector INVALID rather than degrading gracefully.
3. Privileged assignment fields (`assignment_visibility`, `overrides`) that students can't request
   had to be dropped from the request.

**It never reached modules or files** — where most CMU course content actually lives. Getting
there needed a larger connector change the team chose not to make within this sprint's timebox.

## 3. Findings and project decision

**Decision: Modify.** Retrieval-augmented generation over real Canvas content is validated as the
approach — it ran, against live data, producing real indexed content that a retriever could search.
What's not validated is the *substrate*, for three reasons:

1. **Onyx's permission sync requires a commercially-licensed tier.** Onyx CE is MIT, but
   permission sync resolves through `fetch_versioned_implementation` to an enterprise
   implementation under a separate commercial license. An open-source product can't have a
   permission model that requires a commercial license — a contradiction, not a tradeoff.
2. **Per-student isolation runs against Onyx's architecture** — the exact risk named in §1.3 above,
   and the reason [Sprint 2](sprint-02.md) wrote per-student isolation into FR6 as a Must Have
   rather than an implementation detail.
3. **The 11-container deployment is the wrong shape for the user.** "Install Docker and run eleven
   containers" is not a student onboarding flow — directly informed the onboarding requirements
   ([Sprint 2](sprint-02.md) NFR3, NFR4).

**Limitations carried forward, not resolved by this decision:** image-heavy PDF ingestion (§1,
above) is unchanged by the substrate choice — no platform solves it for free, and it remains the
largest open technical risk into Sprint 5. The assignment explainer's explain-vs-draft boundary
(FR8) was not exercised by this prototype at all; retrieval feasibility is not the same claim as
generation-behavior feasibility, and that gap is explicitly open going into Sprint 5.

Full architectural reasoning for the Modify decision: [design spec](../specs/2026-09-14-ssb-design.md)
§10.1.
