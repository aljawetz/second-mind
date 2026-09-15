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

Extended [the design spec](../specs/2026-09-14-ssb-design.md) with the pieces this sprint's rubric
calls for beyond Sprint 3's architecture: an onboarding/first-run flow (§5.4), a sync mechanism for
keeping the index fresh (§5.5), the assignment explainer (§7.1) and its scope boundary against the
deferred assignment helper (§4), session-capture scheduling and triggering (§9.1–§9.3), and a
two-column course-home layout (chat + assignments/artifacts/sessions). Prototyped as a clickable,
hardcoded UI mockup to pressure-test the flow before writing it into the spec.

The extensive technical architecture this sprint's rubric asks for — end-to-end component diagram,
interface definitions, folder structure and data model, Canvas integration detail, and the RAG/LLM
pipeline — lives in **[docs/architecture/](../architecture/overview.md)**, not in this file:

- [Overview](../architecture/overview.md) — system shape, component interfaces, deployment,
  security, reliability.
- [Data model](../architecture/data-model.md) — on-disk folder structure, how a course and its
  weekly schedule are represented, the sync manifest schema.
- [Canvas integration](../architecture/canvas-integration.md) — endpoints used, access
  restrictions found by testing, how sync maps to real API calls.
- [RAG pipeline](../architecture/rag-pipeline.md) — ingestion, chunking, embedding, hybrid
  retrieval, and where LLM provider calls actually happen.

**Not yet covered — gap against this sprint's rubric:** the "Implementation and Integration Plan"
requirement (20% of this sprint's score) asks for component ownership assignment, dependencies,
integration points, and sprint-based milestones. This needs actual team member names and role
assignments, which aren't something to fabricate into a graded deliverable — still open until that
information is supplied.
