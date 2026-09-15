# Sprint 1 — Problem Discovery and Solution Proposal

**Type:** Individual (pre-team) · **Due:** 2026-09-01 · **Points:** 100 · **Status:** Submitted

## Purpose

Identify a real-world problem addressable through an end-to-end software solution, investigate
how it's handled today, and propose a solution a team of 4–6 could realistically prototype in one
semester. Submitted before teams formed — selected individual proposals became the basis for
semester team projects.

## Requirements

| Requirement | Weight |
| --- | --- |
| Problem significance — real, important, evidence-backed | 20% |
| Understanding of users and current solutions | 20% |
| Solution quality and differentiation | 20% |
| Feasibility and scope for a team of 4–6 in one semester | 20% |
| Impact and measurability | 10% |
| Clarity and professionalism | 10% |

## Deliverable

2-page individual proposal: problem definition, prevalence/significance, target users and
stakeholders (user / customer / beneficiary), existing approaches, proposed solution and value
proposition, and 3–5 measurable success criteria (at least one technical, one user/business/social).

## What we did

Submitted 2026-09-01. The specific individual proposal(s) that fed into the team selecting the SSB
project aren't recoverable from Canvas or this repository (repo history starts after team
formation). What follows is a full rewrite of this deliverable, done in Sprint 4 once the whole
project's context existed to write it properly — backed by real research rather than reconstructed
from memory. It supersedes the original submission as the record of the problem SSB solves and why.

---

## 1. Problem and current landscape

### Problem definition

Course material for a given class is scattered across a syllabus PDF, dozens of slide decks,
assignment pages, announcements, and whatever a student manually wrote down in lecture — with no
single place to ask "what did the professor actually say about X" and get a trustworthy, sourced
answer. Graduate students in fast-paced, content-heavy courses feel this most: multiple courses
running in parallel, each with its own scattered material, on a compressed sprint-based semester.
The problem occurs continuously, not just at exam time — every time a student needs to recall or
locate something from a past lecture or reading to move forward on current work.

### Prevalence and significance

- **Adoption of AI for studying is now the norm, not the exception.** 92% of UK undergraduates
  report using generative AI tools, up from 66% the prior year; 88% now use them specifically for
  assessment-related work, up from 53% ([HEPI Student Generative AI Survey
  2025](https://www.hepi.ac.uk/reports/student-generative-ai-survey-2025/)). In the US, 85% of
  college students have experimented with AI for brainstorming, tutoring, or studying
  ([Thesify, 2025 Student AI Survey
  Insights](https://www.thesify.ai/blog/2025-student-ai-survey-insights-ai-tools-for-students-in-higher-education)).
  Students have already decided AI belongs in their workflow — the open question is whether that
  AI is grounded in their actual course material or generic and ungrounded.
- **Course material is genuinely fragmented, and fragmentation has a measured cost.** Learning
  fragmentation — material scattered across notebooks, drives, LMS platforms, and chat threads —
  forces students to pay a repeated "integration cost" every time they need something
  ([AFFiNE, "Why Students Lose Time Switching Between Too Many Study
  Tools"](https://affine.pro/blog/student-lose-time)). Survey data shows students already spread
  studying across multiple disconnected AI tools — 31% for tutoring, 29% for planning, 23% for
  note-taking — rather than one integrated system (Direct Textbook, [2025 survey of student study
  app usage](https://www.directtextbook.com/articles/top-study-apps-students-actually-use/)).
- **Study time is scarcer than institutions assume, which raises the cost of time lost to search.**
  Full-time college students spend roughly 19.3 hours/week on all education-related activity —
  class plus research and homework combined ([Heritage Foundation, using BLS American Time Use
  Survey data](https://www.heritage.org/education/report/big-debt-little-study-what-taxpayers-should-know-about-college-students-time-use)).
  Time spent hunting for the right slide instead of engaging with it is a direct tax on an already
  thin budget.
- **The addressable market is large and growing fast.** The AI-in-education market is valued
  between roughly $8–19B in 2025 depending on scope, projected to grow at a 20–43% CAGR through
  2030 ([Grand View Research](https://www.grandviewresearch.com/industry-analysis/artificial-intelligence-ai-education-market-report);
  [Research and Markets](https://www.researchandmarkets.com/report/education-ai)). Canvas alone
  holds 41% of the North American higher-ed LMS market and roughly 38% of enrolled students
  ([ListEdTech / Cubite, LMS Market Share
  2026](https://cubite.io/blogs/lms-market-share-2026)) — a large, addressable, Canvas-first
  starting point.

### Target users and stakeholders

- **User:** CMU graduate students, self-serve, one install per student.
- **Customer:** the same students — no institutional gatekeeper, no professor approval, no IT
  ticket.
- **Beneficiary:** students directly; instructors indirectly, via fewer repeated questions in
  office hours and on discussion boards.

### How the problem is addressed today

1. **UniFlow Study** — the closest direct competitor. An AI study assistant that syncs Canvas,
   Blackboard, and Moodle, answers questions grounded in course data via a "UniMind" engine, and
   offers live bilingual lecture transcription (Deepgram) and a writing assistant
   ([uniflowstudy.com](https://www.uniflowstudy.com/)). It is proprietary and cloud-hosted, and
   meters usage: the free tier caps out at 30 AI conversations/month and one course import; paid
   tiers run $12.80–$39.20/month for more conversations and transcription hours
   ([uniflowstudy.com/pricing](https://www.uniflowstudy.com/pricing)). It does not generate mock
   tests, mindmaps, or flashcards from indexed material.
2. **A do-it-yourself stack of disconnected tools** — general-purpose ChatGPT for Q&A (not grounded
   in the student's specific course material, no citations, real hallucination risk), Otter.ai or
   manual note-taking for lecture capture, and Quizlet/Anki for flashcards. This is exactly the
   fragmentation problem documented above: it works, but the student pays the integration cost of
   stitching four separate tools together by hand.
3. **Paying for a human** — office hours, TA sessions, or private tutoring. Tutoring averages
   $25–$80/hour nationally and can run $60–$150/hour at the college level
   ([Tutors.com, 2026 Tutoring Prices](https://tutors.com/costs/)) — effective, but not scalable to
   "I have a question about last Tuesday's lecture at 11pm."

## 2. Proposed solution

SSB (Student Second Brain) is one app per student that ingests their real Canvas course material,
captures their lectures, answers questions with citations back to the source, and generates the
study material students otherwise build by hand — mock tests, mindmaps, slides, flashcards. Inputs
are the student's own Canvas token (their existing course access, nothing more) plus their
lecture recordings and notes. Processing is retrieval-augmented generation over a private,
per-student, on-disk index — never a shared cloud corpus. Output is an answer-first response with
inline citations to the specific page, file, or transcript moment it came from, or a generated
study artifact traceable the same way.

### Value proposition

**For** a CMU graduate student juggling several content-heavy courses' worth of scattered
material, **who struggles with** finding the right slide, transcript, or reading exactly when they
need it, **our proposed solution provides** grounded, cited answers and auto-generated study
material **by** indexing each student's own Canvas content, lecture recordings, and notes into a
private, on-disk store, **unlike** UniFlow Study and the ChatGPT-plus-Otter-plus-Quizlet stack,
**which** either meter access behind a subscription while keeping data in someone else's cloud, or
force students to manually integrate several disconnected tools themselves.

### Why someone would choose it over the alternatives

Open source and self-hosted beats UniFlow Study on cost (unmetered vs. metered conversations) and
data ownership (the student's own machine vs. vendor cloud) — a meaningful difference for
recorded lectures specifically, which touch instructor and classmate privacy. Against the DIY
stack, one integrated, course-aware system beats four disconnected tools on the fragmentation cost
documented above. And unlike paying a human, it's available at 11pm for the cost of self-hosting.

## 3. Measuring impact

- **Citation groundedness rate** *(technical)* — % of answers where the cited source actually
  supports the claim, hand-graded on a fixed question set.
- **Retrieval precision@k** *(technical)* — against a set of known expected sources.
- **Artifact groundedness** *(technical)* — % of generated mock-test questions answerable from
  their cited source; graded separately because a hallucinated mock-test question is worse than no
  mock test at all.
- **Return usage during exam weeks** *(user/social)* — the honest signal that generated artifacts
  are actually being used to study, not generated and abandoned.
- **Pre/post self-reported confidence on the material** *(user/social)* — whether students report
  feeling more prepared after using SSB versus their prior study routine.

At least one technical metric (citation groundedness) and one user-impact metric (return usage
during exam weeks) anchor the evaluation, per the assignment rubric.

## References

- HEPI, [Student Generative AI Survey 2025](https://www.hepi.ac.uk/reports/student-generative-ai-survey-2025/)
- Thesify, [2025 Student AI Survey Insights](https://www.thesify.ai/blog/2025-student-ai-survey-insights-ai-tools-for-students-in-higher-education)
- AFFiNE, [Why Students Lose Time Switching Between Too Many Study Tools](https://affine.pro/blog/student-lose-time)
- Direct Textbook, [Top Study Apps Students Actually Use: 2025 Survey Results](https://www.directtextbook.com/articles/top-study-apps-students-actually-use/)
- The Heritage Foundation, [Big Debt, Little Study: What Taxpayers Should Know About College Students' Time Use](https://www.heritage.org/education/report/big-debt-little-study-what-taxpayers-should-know-about-college-students-time-use)
- Grand View Research, [AI in Education Market Report](https://www.grandviewresearch.com/industry-analysis/artificial-intelligence-ai-education-market-report)
- Research and Markets, [Artificial Intelligence in Education Market Size & Trends](https://www.researchandmarkets.com/report/education-ai)
- ListEdTech / Cubite, [LMS Market Share 2026](https://cubite.io/blogs/lms-market-share-2026)
- UniFlow Study, [uniflowstudy.com](https://www.uniflowstudy.com/) and [uniflowstudy.com/pricing](https://www.uniflowstudy.com/pricing)
- Tutors.com, [2026 Tutoring Prices](https://tutors.com/costs/)
