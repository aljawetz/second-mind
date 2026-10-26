# Sprint 8 — Robustness, Responsible AI, and System Improvement

**Type:** Team · **Due:** 2026-10-27 · **Points:** 100 · **Status:** Planned

## Purpose

Strengthen the system based on evidence rather than expanding project scope.

## Requirements

| Requirement | What Must Be Demonstrated | Weight |
| --- | --- | --- |
| Evidence-Driven System Improvement | Implement the highest-priority improvements identified through technical and stakeholder validation; demonstrate measurable improvement | 40% |
| Robustness and Reliability Testing | Stress-test under relevant conditions: noisy/missing data, unusual inputs, model uncertainty, API failures, increased load, out-of-distribution cases | 35% |
| Responsible Deployment | Address relevant security, privacy, bias/fairness, hallucination, explainability, accessibility, misuse, and failure-consequence risks; document remaining limitations | 25% |

## Deliverable

Improved end-to-end system plus a 3–4 page robustness/responsible-deployment report with
before/after evidence.

## Relevant scope

This is the explicit checkpoint named in [the design spec](../specs/2026-09-14-second-mind-design.md) §4
for the assignment-explainer / assignment-helper boundary (§7.1) and the privacy model (§6). §11's
risks — image-heavy PDF ingestion, artifact groundedness, per-student storage cost, recording
consent — are the candidates for the robustness half of this sprint.

## Plan

### Goal

Make Second Mind's answers better in ways we can measure, make it hold up under bad data and
unusual use, and make it safe to hand to students. We improve what we already have instead of
adding new features.

Grading weights: evidence-driven improvement 40%, robustness 35%, responsible deployment 25%.
Due Tuesday, October 27, 2026 at 10:00 AM PT.

### The PR stack

Each step is one PR, stacked on the one before it.

| Step | PR | What it does |
| --- | --- | --- |
| 1 | #21 | Search-only eval: score search results (recall@5, precision@5) on real Canvas data without calling a model |
| 2 | #22 | Merge keyword and meaning search results by rank (reciprocal rank fusion) |
| 3 | #23 | Rerank the merged results with a small local model and drop weak matches (minimum score) |
| 4 | next | Rewrite the question before searching, and suggest "Did you mean" topics when nothing matches |
| 5 | next | Robustness tests: noisy or missing data, unusual inputs, API failures, load, out-of-distribution questions |
| 6 | next | Responsible AI: keep graded quizzes out of the index, sign out and delete all data, refuse to do graded work (explainer, not helper), recording consent, and docs |
| 7 | next | Final report in `docs/evaluations/2026-10-sprint8/` |

### Status so far

Search-only eval on real Canvas data (sprint7 question set, 25 questions, 22 with an expected source):

| Step | recall@5 | precision@5 | Notes |
| --- | --- | --- | --- |
| 1, baseline | 91% (20/22) | 36.8% | sometimes returned 6 results |
| 2, merge results | 91% (20/22) | 35.5% | always 5 results; no real change |
| 3, rerank (MiniLM, cutoff 0.03) | 86% (19/22) | 42.4% (40.5% if empty counts as 0) | V9, the question the course never covers, now returns 0 results; search takes 0.41s median |

Step 3 lost one question of recall and gained about 7 points of precision. Its cutoff was tuned on
this same question set, so we still need to check it on new questions.

### Proof rule

- Every PR has proof in its description: test output, real Canvas runs repeated to show they are
  stable, and reports or screenshots where they help.
- We move to the next step only when that proof is valid.
- Tests and evals use real Canvas data, not made-up data.

### Making the experiments more trustworthy

- **Held-out questions.** Write 10 to 15 new questions the way students actually ask them. We never
  tune anything on this set; it is only for checking.
- **Better labels.** Mark a result as relevant if it contains the fact that answers the question,
  not because its file name matches. (Today the midterm slide with the date counts as a miss
  because the answer key only accepts the syllabus.)
- **Full-answer eval.** Run the whole chat with OpenAI and check that the answer is correct, the
  citations are real, and it says "I don't know" when it should.
- **Honest numbers.** Always report counts (like 19/22), not only percents. A one-question gap is a
  tie at this size. Report precision both ways: with empty results skipped and with empty results
  counted as 0.

## What we did

TBD — fill in once this sprint is underway.
