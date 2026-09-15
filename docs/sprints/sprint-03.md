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

## What we did

Submitted 2026-09-15 (2 attempts). Built a real proof of concept against self-hosted
[Onyx](https://github.com/onyx-dot-app/onyx): a 1,068-line native `CanvasConnector` implementing
Onyx's `CheckpointedConnectorWithPermSync` and `SlimConnectorWithPermSync` interfaces, running in a
live Onyx v4.7.3 Standard deployment against a real CMU course (49797).

It ran — indexing courses, pages, assignments, and announcements — but only after three fixes to
survive a student-scoped token (404s on disabled Pages tabs skipping whole courses, per-stage 403s
marking the connector INVALID, privileged assignment fields students can't request). It never
reached modules or files, where most CMU course content actually lives.

**Decision: Modify.** Retrieval-augmented generation over real Canvas content is validated and
stays the approach. The substrate changes, for three reasons: Onyx's permission sync requires a
commercially-licensed tier, which an open-source product can't depend on; per-student isolation
runs against Onyx's shared-corpus architecture; and its 11-container deployment is the wrong shape
for software a student installs. Full reasoning: [design spec](../specs/2026-09-14-ssb-design.md)
§10.1.

The detailed working notes and connector patch from this sprint were removed from the repository
in a later cleanup once the Modify decision and its reasoning were folded into the design spec —
§10.1 is the surviving record.
