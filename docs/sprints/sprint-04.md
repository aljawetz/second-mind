# Sprint 4 — System Architecture and Implementation Plan

**Type:** Team · **Due:** 2026-09-22 · **Points:** 100 · **Status:** In progress

## Purpose

Design the complete end-to-end system before individual components are developed independently.

## Requirements

| Requirement | What Must Be Demonstrated | Weight |
| --- | --- | --- |
| End-to-End Architecture | Show how user/input, data, AI/processing, backend/services, storage, interface/output, and external systems work together; include relevant cloud or on-prem infrastructure | 45% |
| Technical Design and Interfaces | Define major components, data flows, APIs/interfaces, technology choices, deployment approach, and relevant reliability, security, privacy, and responsible-AI considerations | 35% |
| Implementation and Integration Plan | Assign component ownership, identify dependencies and integration points, define sprint-based milestones for completing the system | 20% |

## Deliverable

4–6 page technical design document including architecture diagram, interface definitions, and
implementation milestones.

## What we did (so far)

Extended [the design spec](../specs/2026-09-14-second-mind-design.md) with the pieces this sprint's rubric
calls for beyond Sprint 3's architecture: an onboarding/first-run flow (§5.4), a sync mechanism for
keeping the index fresh (§5.5), the assignment explainer (§7.1) and its scope boundary against the
deferred assignment helper (§4), session-capture scheduling and triggering (§9.1–§9.3), and a
two-column course-home layout (chat + assignments/artifacts/sessions). Prototyped as a clickable,
hardcoded UI mockup to pressure-test the flow before writing it into the spec.

**The deliverable is [the technical design document](../architecture/design-document.md)** — the
consolidated 4–6 page design: end-to-end architecture diagram, interface definitions, technology
choices, deployment, reliability/security/privacy/responsible-AI, and the ownership, dependency, and
milestone plan. The detailed documents in **[docs/architecture/](../architecture/overview.md)** are
its appendices:

- [Design document](../architecture/design-document.md) — the submitted deliverable.
- [Overview](../architecture/overview.md) — system shape, component interfaces, deployment,
  security, reliability.
- [Data model](../architecture/data-model.md) — on-disk folder structure, how a course and its
  weekly schedule are represented, the sync manifest schema.
- [Canvas integration](../architecture/canvas-integration.md) — endpoints used, access
  restrictions found by testing, how sync maps to real API calls.
- [RAG pipeline](../architecture/rag-pipeline.md) — ingestion, chunking, embedding, hybrid
  retrieval, and where LLM provider calls actually happen.
- [Implementation plan](../architecture/implementation-plan.md) — a sequenced build order (15
  steps, Sprint 5–6) with dependencies and a concrete test for each one.

Dependencies, integration points, and milestones are written down in
[docs/architecture/implementation-plan.md](../architecture/implementation-plan.md) (a concrete
"Depends on:" per step) and in the sprint table on the [README](../../README.md#project-context)
(sprint-based milestones). **Component ownership**, the last open piece of this requirement, is
below — team: 3 PMs (Richa, Lakshita, Shatakshi), 3 Engineers (Arthur, Aaron, Yongje).

### Engineering — owns building and maintaining the technical components

| Owner | Components |
| --- | --- |
| Arthur | App shell & sidecar infra ([Steps 0–1](../architecture/implementation-plan.md)); Credentials & Canvas integration (Steps 2–3); Error handling & course management (Step 13); Contribution & distribution pipeline (license, CI, release) |
| Aaron | Ingestion, embedding & retrieval pipeline (Steps 4–6, and the cross-step integration check); Sync mechanism (Step 7); Generation/Q&A backend (Step 8) |
| Yongjie | Q&A frontend wiring (Step 9); Assignment explainer (Step 10); Session capture (Step 12); **Study artifacts (Step 11 — not yet built, next up)** |

### Product — owns a cross-cutting responsibility spanning multiple steps, not a single component

| Owner | Responsibility |
| --- | --- |
| Richa | Responsible AI & scope boundaries — the explain-never-draft line (design spec §7.1), recordings-stay-private, web-search labeling; validates Steps 8, 10, 12 against these |
| Lakshita | Testing & calibration rigor — the grounding-cutoff calibration methodology, the regression-fixture discipline, "verify against real data, not mocks" across all steps |
| Shatakshi | Docs, specs & external readiness — keeping `docs/architecture/*.md` accurate against what's actually built, the contribution & distribution plan's PM-facing pieces (README, CONTRIBUTING, issue templates), later sprints' user/impact validation |

This mirrors each step's own **Owner:** line in
[implementation-plan.md](../architecture/implementation-plan.md).
