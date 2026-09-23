# Sprint 2 — Problem Validation, Requirements, and MVP Scope

**Type:** Team · **Due:** 2026-09-08 · **Points:** 100 · **Status:** Submitted

## Purpose

Convert the selected individual proposal into a validated team project with a clearly defined
semester scope.

## Requirements

| Requirement | What Must Be Demonstrated | Weight |
| --- | --- | --- |
| Problem, User, and Need Validation | Strengthen evidence the problem is real; refine target users/stakeholders; identify the most important unmet needs and 2–4 core use cases; revise assumptions from the individual proposal where needed | 35% |
| Requirements and MVP Definition | Define testable functional and relevant non-functional requirements; prioritize as Must Have / Should Have / Could Have / Out of Scope; specify the end-to-end MVP | 45% |
| Feasibility and Success Measures | Demonstrate the scope is realistic for one semester; define measurable technical and industry/social-impact success criteria | 20% |

## Deliverable

3–4 page team report plus a concise Semester MVP Contract defining what the team commits to
deliver.

---

## 1. Problem, user, and need validation

### Strengthened evidence

Beyond the adoption, fragmentation, and market evidence gathered in [Sprint
1](sprint-01.md), two findings specifically validate *how* Second Mind needs to solve the problem, not
just that the problem exists:

- **Citations aren't a nice-to-have — they're the #1 trust blocker.** Misinformation is students'
  most prominent AI concern (73%), and students specifically cite "the absence of source
  citations" as a source of wariness toward AI answers ([thematic analysis, AI Hallucination from
  Students' Perspective](https://arxiv.org/html/2602.17671v1)). Perceived accuracy is what drives
  willingness to actually use an AI tool ([MDPI, Trust in Generative AI
  Tools](https://www.mdpi.com/2078-2489/16/7/622)). This validates answer-first-with-citations as
  the core mechanic, not a differentiator layered on afterward.
- **Recording privacy is a real, documented constraint, not overengineering.** Classroom
  recordings that identify a student are protected educational records under FERPA, and
  institutions maintain explicit consent processes for lecture capture because of it ([Cornell,
  Classroom Privacy and Recording Guidelines](https://teaching.cornell.edu/teaching-resources/inclusion-accessibility/classroom-privacy-and-recording-guidelines);
  [University of Michigan, Recording Privacy
  Concerns](https://safecomputing.umich.edu/protect-privacy/privacy-u-m/videoconferencing/recording-privacy-concerns)).
  A private-by-default, no-sharing-path stance is the only one defensible without building a
  consent mechanism — validating the privacy model rather than assuming it.

### Refined users and stakeholders

- **User:** any student whose courses run on Canvas, self-serve, one install per student. CMU is
  the pilot install base, not a scope limit.
- **Customer:** the same students — no institutional gatekeeper, no professor approval, no IT
  ticket.
- **Beneficiary:** students directly; instructors indirectly, via fewer repeated questions in
  office hours and on discussion boards.
- **Additional stakeholders surfaced during validation:** instructors and classmates, whose
  consent and privacy the recording feature touches even though they aren't Second Mind's user; the
  student's institution's Canvas administration, whose API access policy bounds what a student
  token can request (directly relevant after Sprint 3's finding that student-scoped tokens hit
  403s on privileged fields).

### Core use cases (validated)

1. **Ask a grounded question about course material** and get an answer-first response with
   citations back to the specific page, file, or lecture moment.
2. **Attend a lecture** — capture, transcribe, and take notes in one place, indexed automatically
   the moment class ends.
3. **Generate a study artifact** (mock test, mindmap, flashcards, or slides) ahead of an exam,
   from material actually covered in the course.
4. **Get an assignment explained** — what a specific prompt is asking and which lecture material
   it draws on — without it drafting any part of the submission.

### Assumptions revised from the individual proposal

The individual proposal's framing was aspirational about scope; validation narrowed it in two
ways: (1) grounding and citations moved from "a feature" to *the* core mechanic, given how
strongly students weight source-citation and accuracy; (2) the recording-privacy stance moved from
implicit to an explicit, non-negotiable requirement, given FERPA's real bite on identifiable
classroom recordings.

## 2. Requirements and MVP definition

### Functional requirements

**Must have**

- **FR1** — Let the student paste their own Canvas API token and LLM API key during onboarding;
  store both locally and never transmit them to any Second Mind-operated service (see NFR1).
- **FR2** — Ingest a student's Canvas course content (pages, assignments, announcements, modules,
  files) using the student's own token.
- **FR3** — Answer natural-language questions about indexed course material with inline citations
  to source.
- **FR4** — State explicitly when indexed material doesn't support an answer, rather than falling
  back to open-domain knowledge.
- **FR5** — Auto-create a session page at class time; record, transcribe locally, and provide a
  notes editor alongside the transcript.
- **FR6** — Keep retrieval/index physically isolated per student (own directory), not a shared
  corpus with query filters.
- **FR7** — Fetch grades, deadlines, and submission status live per request; never persist or
  index them.
- **FR8** — Assignment explainer: help the student understand a specific assignment using grounded
  information — break down the prompt and cite relevant course material — and never draft any
  part of the submission. (Not the deferred assignment *helper* in Out of Scope, which drafts
  answers — see design spec §7.1 for the boundary between the two.)

**Should have**

- **FR9** — Generate study-artifact types (mock test, mindmap, flashcards, slides) from indexed
  material, cited to source.
- **FR10** — Multi-course support in the sidebar, across at least two courses.

**Could have**

- **FR11** — Pre-class prep brief generated from the prior session's transcript plus assigned
  readings.
- **FR12** — Web-search fallback when course material doesn't cover a question, visibly labeled
  and never blended into a course-grounded answer.
- **FR13** — Piazza as a source, if an official public API becomes available.
- **FR14** — Assignment gamifier: break an assignment into smaller guided blocks (Duolingo-style),
  where the student answers or fills in simpler chunks with explanations, and the completed
  assignment is assembled from those answers. **Flag:** this sits closer to the deferred
  assignment *helper* than the explainer does — the guided answers could end up constituting the
  submission itself, just built interactively rather than drafted outright. Needs a
  responsible-AI review against the §7.1 boundary before any implementation, not just an
  engineering design.
- **FR15** — Calendar integration: connect to Google Calendar to fetch events.
- **FR16** — External reading scraper: pull text from external reading websites (assigned links,
  not indexed course files) to add to context-based answers. Must follow the same labeling rule as
  FR12 — visibly marked as outside the course-grounded index, never silently blended in — and
  needs a look at each source's terms of service before scraping it, not just a technical build.

**Out of scope this semester**

- An assignment *helper* that drafts answers, code, or any submittable text.
- A writing assistant.
- Any cross-student or shared knowledge base.
- Non-Canvas LMS support (Blackboard, Moodle).

### Non-functional requirements

- **NFR1 (Privacy)** — Recordings, notes, and documents never leave the student's machine; Canvas
  token and LLM API key are stored locally and never transmitted to any Second Mind-operated service.
- **NFR2 (Groundedness)** — Citation groundedness and artifact groundedness are tracked as
  first-class, separately-evaluated metrics, not assumed from retrieval quality alone.
- **NFR3 (Onboarding)** — First run (connect credentials → select courses → index → land in app)
  completes without manual configuration files, so someone outside the development team can
  realistically install and use it.
- **NFR4 (Deployment)** — Runs on a student's own machine without a multi-container server stack.
- **NFR5 (Responsiveness)** — Retrieval and Q&A stay conversational — fast enough for a real-time
  study session, not a batch job.

### End-to-end MVP

One integrated flow: connect Canvas and LLM credentials → select and index real courses → ask
grounded, cited questions → attend a session (capture + notes). Grades and deadlines are read
live, never indexed; recordings and notes stay private with no sharing path. Study-artifact
generation is a Should Have, layered on once this core flow is solid.

### Semester MVP Contract

By Sprint 6, the team commits to an end-to-end alpha where a Canvas-using student can: connect their own
Canvas and LLM credentials; select and index at least two real courses; ask questions about
indexed material and receive answer-first, cited responses; have at least one class session
auto-captured, transcribed, and made note-taking-ready; and get a grounded explanation of a
specific assignment's prompt. Grades and deadlines are read live, never indexed. Recordings and
notes stay private to the student, with no sharing path. Study-artifact generation, additional
artifact types, pre-class prep briefs, and any capability that drafts submittable work are
explicitly Should/Could/Out of Scope — not committed.

## 3. Feasibility and success measures

**Feasibility for one semester.** Sprint 3's finding (§ [sprint-03.md](sprint-03.md)) already
tested the highest-risk technical assumption — RAG over real Canvas content — and validated it.
Scoping the committed MVP to three pillars (Q&A, lecture capture, assignment explainer), with
study artifacts as Should Have layered on top, across a 4–6 person team over a 9-sprint semester
matches the rubric's own guidance: a smaller system that works end-to-end beats an
ambitious one that doesn't.

**Success measures**

- **Citation groundedness rate** *(technical)* — % of answers where the cited source actually
  supports the claim.
- **Retrieval precision@k** *(technical)* — against a set of known expected sources.
- **Artifact groundedness** *(technical)* — % of generated mock-test questions answerable from
  their cited source, graded separately from answer groundedness.
- **Return usage during exam weeks** *(user/social)* — whether generated artifacts are actually
  used to study, not generated and abandoned.
- **Pre/post self-reported confidence on the material** *(user/social)*.

## References

- arXiv, [AI Hallucination from Students' Perspective: A Thematic Analysis](https://arxiv.org/html/2602.17671v1)
- MDPI, [Trust in Generative AI Tools: A Comparative Study of Higher Education Students, Teachers, and Researchers](https://www.mdpi.com/2078-2489/16/7/622)
- Cornell Center for Teaching Innovation, [Classroom Privacy and Recording Guidelines](https://teaching.cornell.edu/teaching-resources/inclusion-accessibility/classroom-privacy-and-recording-guidelines)
- University of Michigan Safe Computing, [Recording Class Activities: Privacy Concerns](https://safecomputing.umich.edu/protect-privacy/privacy-u-m/videoconferencing/recording-privacy-concerns)
