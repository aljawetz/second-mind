# Canvas AI Tutor — Design Spec

> **SUPERSEDED (2026-09-14).** This project is now **SSB — Student Second Brain**, an open-source
> alternative to UniFlow Study. The current spec is
> [`2026-09-14-ssb-design.md`](2026-09-14-ssb-design.md).
>
> What changed: the scope widened from a Socratic Canvas tutor to a three-pillar second brain
> (grounded Q&A, lecture capture, study-artifact generation); Socratic became a toggle rather than
> the default; and the Onyx substrate was dropped per the Sprint 3 **Modify** decision (see §10.1
> of the new spec). Kept for history.

Course: 49797, Special Topics: Advanced AI for Industry and Society (Fall 2026)
Date: 2026-09-11

## 1. Thesis

An AI tutor, built on self-hosted [Onyx](https://github.com/onyx-dot-app/onyx) wired to Canvas via
its MCP connector support, that answers questions strictly from a specific course's real material
and teaches Socratically instead of just handing over answers.

## 2. Users

- **User**: students enrolled in a given course.
- **Customer**: the same students, self-serve — no institutional gatekeeper required for the MVP.
- **Beneficiary**: students directly (learning outcomes); TAs/professors indirectly (fewer
  repetitive office-hours questions).

## 3. Architecture

```
Canvas (source of truth)
   │
   ▼
canvas-api MCP server  ──────►  Onyx (self-hosted, MIT, Docker)
                                   - one index/"space" per course
                                   - MCP-based connector/action pulls
                                     syllabus, pages, files per course
                                   - hybrid keyword + vector retrieval
                                   - chat UI (Onyx's own, course-scoped)
   ▲
   │
Student (self-serve opt-in per course)
```

- **One Onyx index per course**, populated only with that course's public materials (syllabus,
  pages, files/slides). Any student enrolled in the course can query it.
- This is the deliberate workaround for Onyx community edition's lack of fine-grained per-student
  document permissions: since nothing student-specific ever enters an index, there's nothing to
  leak.
- **Frontend for the MVP**: Onyx's own built-in chat UI, scoped/branded per course, rather than a
  custom frontend built from scratch. A custom frontend is a post-MVP polish item, not a Sprint 3
  blocker.
- **LLM**: pluggable via Onyx's model abstraction (Anthropic/OpenAI/self-hosted). Start with a
  strong hosted model; swapping later doesn't require re-engineering the pipeline.
- **Onboarding**: student self-serve. Any enrolled student can point the tool at a course they're
  in (using their own Canvas token/OAuth), and it indexes that course's public materials for every
  other enrolled student too. No professor approval required to launch.

## 4. Tutor behavior

- Default mode is **Socratic**: guiding questions first, not direct answers.
- Escape hatch: reveals the direct answer after a few exchanges, or immediately on explicit
  request ("just tell me"). Full Socratic-only would frustrate students who need a fast answer
  under time pressure — this hatch keeps the pedagogical positioning without being rigid.
- Every answer must **cite the specific Canvas page/file** it drew from. If a claim can't be
  grounded in indexed material, the tutor says so rather than falling back to open-domain
  knowledge. This is the core trust/differentiation property vs. pointing a generic LLM at a
  syllabus.

## 5. The genuinely risky part: ingestion

Slide decks and PDFs on Canvas are frequently image-heavy. This was directly observed while
scoping this project: `read_course_file` on a real course PDF (`CatherineFang_Bio.pdf`) returned
raw base64 bytes, not usable text — only downloading and reading the actual file worked, and even
then the content is images-with-text-overlay, not clean extractable text. Turning this kind of
material into properly chunked, retrievable content for Onyx is an open technical question, not a
solved one, and is the single biggest feasibility risk in this design.

## 6. Sprint 3 baseline / proof of concept

1. Stand up Onyx locally (or on a small VM).
2. Connect the `canvas-api` MCP server as a data source.
3. Index one real course's content end-to-end.
4. Hand-write ~15–20 real student questions about that course.
5. Run them through the pipeline and manually grade:
   - Was the right source retrieved?
   - Does the citation actually support the answer?
   - Did the Socratic prompting behave as intended (guided, then revealed on request)?
   - Did image-heavy slide decks index usably at all, or did they need a separate OCR
     pre-processing step before ingestion?
6. **Proceed / Modify / Pivot**: if slide-deck ingestion fails badly, that's a legitimate
   **Modify** finding — e.g., scope the MVP to text-based course content (pages, docs) first,
   with image-heavy slide support as a later stretch goal — rather than a project-killing Pivot.

## 7. Success metrics

- **Technical**: citation-groundedness rate (% of answers where the cited source actually
  supports the claim, hand-graded on the Sprint 3 question set); retrieval precision@k.
- **User / impact**: return usage during exam weeks; pre/post self-reported confidence on the
  material; if a pilot course allows it, reduction in repeat questions on the discussion board or
  in office hours after the tutor becomes available.

## 8. Differentiation

- **vs. generic ChatGPT/Claude**: hard-grounded to the actual course's material only, with
  citations; won't answer from outside the syllabus, reducing hallucination and wrong-course-
  content risk.
- **vs. Khanmigo / StudyFetch / similar AI tutors**: those require manual upload of material by
  the student or instructor. This auto-syncs directly from Canvas and stays current as the
  professor adds content through the semester, with no re-upload step.
- **vs. Onyx itself**: Onyx is a general-purpose enterprise RAG platform. The product here is the
  specific configuration on top of it — Canvas-scoped per-course indices via MCP, Socratic
  tutoring prompt design, a self-serve per-course sharing model, and an evaluation harness for
  groundedness — not a claim to have built the retrieval engine.

## 9. Known risks / open items (to state honestly in the proposal)

- **RBAC gap**: Onyx community edition's lack of fine-grained per-student permissions is
  mitigated by the public-per-course-index design, but this is a deliberate constraint, not an
  oversight — worth naming explicitly.
- **Content consent**: even under student self-serve, a professor could object to their material
  being indexed and shared this way without being asked. A cheap opt-out/takedown mechanism is
  worth building early as insurance against a real objection.
- **OCR / slide-deck ingestion quality** is unproven — this is exactly what Sprint 3's baseline
  is designed to test.
- **"Did it teach well?" is hard to auto-evaluate.** Plan on a human-graded rubric sample rather
  than a fully automated metric for the Socratic-tutoring quality claim.
