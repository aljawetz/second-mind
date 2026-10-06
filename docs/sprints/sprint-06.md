# Sprint 6 — End-to-End Alpha System

**Type:** Team · **Due:** 2026-10-06 · **Points:** 100 · **Status:** Planned

## Purpose

Integrate the project's major components into the first functioning version of the complete
solution.

## Requirements

| Requirement | What Must Be Demonstrated | Weight |
| --- | --- | --- |
| End-to-End Integration | A realistic input passes through the complete system and results in a meaningful user-facing output or action; all major components operate together | 50% |
| Must-Have Functionality and Testing | Implement the Must Have requirements at alpha level; test normal, edge, and failure scenarios | 30% |
| Integration Assessment and Next Sprint Plan | Identify integration failures, bottlenecks, technical debt, usability problems, and the highest-priority improvements for the next iteration | 20% |

## Deliverable

Live end-to-end alpha demonstration plus a short integration/testing report.

## Relevant scope

Per [the design spec](../specs/2026-09-14-second-mind-design.md) §4, this is where lecture capture (§9)
and study artifacts (§8) come online alongside Sprint 5's Q&A, and the onboarding flow (§5.4) gets
wired to a real backend instead of the mockup's hardcoded data.

## What we did

**Integration.** Every major part now runs together on a real course: Canvas sync, cited chat,
the assignment explainer, session capture, agent memory, and the new study artifacts. On 2026-10-04
we ran the whole chain on 49797 with real Canvas data and gpt-4o-mini: sync, cited questions, an
assignment explanation, a recorded lecture that was then searchable in chat, and a quiz built from
that week's slides plus the recording. All 24 steps worked.

**New this sprint.** Quizzes and flashcards modelled on NotebookLM's, each item cited to its
passage and checked (design spec §8, [PR #19](https://github.com/aljawetz/second-mind/pull/19)).
Sync now also reads Word, Excel and text files, which were missing from chat and study before.

**Testing.** 423 backend tests, plus a normal, edge and failure case per Must Have in the dry run.
FR4, FR6 and FR7 pass. FR1, FR3 and FR8 work with gaps. FR5 is partial: recording starts by hand,
not at class time, and a real classroom recording is still untested.

**What we found.** In one hand-graded quiz, 6 of 10 questions were supported by the passage they
cite. The check meant to catch the rest missed them, and fixing it is Sprint 7's first task.
Onboarding also checks only a key's format, the explainer gave no source pointers for one
assignment, and silent or broken recordings don't say what went wrong.

Report: [docs/evaluations/sprint-6-deliverable.md](../evaluations/sprint-6-deliverable.md).
Rerun the dry run: `backend/scripts/e2e_dry_run.py`.
