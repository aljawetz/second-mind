# Checking the answer judge against hand grades

**Date:** 2026-11-13. **Plan:** RAG gaps plan, task 6 (`docs/plans/2026-11-09-rag-course-gaps.md`).

## Summary

On 20 chat turns (40 answers) graded by hand, the gpt-4o judge picked the same better answer as the person on **all 20 turns**. Its single-answer grades matched on **32 of 40** answers. All 8 disagreements go the same way: the judge is one step stricter, and never more lenient. So the judge can be trusted for comparing a system against a baseline. Its good/OK/bad counts are a lower bound on how a person would grade.

This sample has a clear limit. The shipped chat and a no-search baseline are easy to tell apart, so the sample doesn't show that the judge can separate two close versions of the chat.

## Why

Sprint 7 hand-checked 10 answers and agreed with the judge on only 4 of them. Sprint 8 called the automatic grader "too noisy to trust" and listed "have a person grade a fixed sample" as a next step. The final report needs answer-quality numbers that can be believed.

## Method

- **Answers.** The `sprint9-chat` set has 14 chats and 40 turns on courses 55016 and 56350, each turn with a gold fact checked word for word in the index. Two systems answered every turn:
  - the shipped chat (`ask_modes_eval.py` mode E: search, follow-up rewrite, reranker)
  - the no-search baseline (mode G: the same model and no course text, which is what a student gets from a plain chatbot)

  Both used **gpt-4o-mini** to keep cost down, not the app's default gpt-5-mini. The judge is checked on these answers. They are not a measure of the shipped app. The run cost $0.014.
- **Sample.** 20 of the 40 turns, picked with a fixed seed. Chats were split into a **tuning half** and a **reporting half** (10 turns each), so that the judge prompt could be adjusted on one half and checked once on the other. A chat's turns are never split across halves.
- **Hand grades.** One team member who knows the courses graded on a local page:
  - It showed the question, the earlier questions in the chat, the gold answer, and both answers in random order (A/B).
  - It didn't say which system wrote which answer, and the judge's grades were not available while grading.
  - Each answer got good, OK or bad, using the judge's own definitions. Then the grader picked the better answer, or a tie.
  - Two picks contradicted the grader's own grades. The grader confirmed they were misclicks, and they were corrected before the reporting half was scored.
- **Judge, two formats** (gpt-4o, temperature 0):
  - **Pointwise:** the existing `ask_modes_eval.judge()`, which grades one answer good, OK or bad against the gold answer.
  - **Pairwise:** the format from the RAG course. Both answers are shown side by side, and the judge gives its verdict first. It is asked in both orders, and a verdict that changes with the order counts as a tie.

## Results

| | Tuning half (10 turns) | Reporting half (10 turns) | All 20 |
| --- | --- | --- | --- |
| Pointwise grades the same | 18 of 20 | 14 of 20 | 32 of 40 |
| Cohen's kappa (agreement beyond chance) | 0.82 | 0.52 | |
| Better answer, from the pointwise grades | 10 of 10 | 10 of 10 | 20 of 20 |
| Better answer, pairwise judge | 10 of 10 | 10 of 10 | 20 of 20 |

- **Order didn't sway the pairwise judge.** Its verdict changed with the order on 0 of 20 turns.
- **Grade totals:**

  | | Shipped chat (person) | Shipped chat (judge) | No-search baseline (person) | No-search baseline (judge) |
  | --- | --- | --- | --- | --- |
  | good | 20 | 18 | 0 | 0 |
  | OK | 0 | 2 | 6 | 0 |
  | bad | 0 | 0 | 14 | 20 |

### Where the judge and the person differ

All 8 disagreements are the judge grading one step lower:

- **6 no-search answers, person OK, judge bad.** Each one gives generic advice instead of the course's fact, such as typical peer-review steps or common score scales, often adding "check your course materials". The rubric supports both readings: "OK = unhelpful or incomplete" and "bad = fails to answer something it should have". Sprint 7's check showed the same split.
- **2 shipped answers, person good, judge OK.** These were "what goes into the interaction framework?" and "what do I install for Zotero?". Both state the gold facts. The judge seems to have marked them down for being incomplete or for extra detail.

The disagreements are systematic, not random. That is why the tuning half (kappa 0.82) and the reporting half (0.52) differ: the reporting half happened to contain more no-search answers that sit on the OK/bad line.

## Decision

- **Keep the pointwise judge as the default** in `ask_modes_eval.py`. Both formats agreed with the person equally often on which answer is better (20 of 20). Pointwise also gives each answer a grade and costs the same: two calls per turn.
- **The judge prompt was not changed.** The only pattern on the tuning half was the OK/bad line, on 2 answers. Changing the prompt for 2 answers would have been overfitting, and the reporting half shows the same pattern anyway.
- **How to read judge numbers in the final report:**
  - Comparisons against a baseline (which system is better) can be trusted.
  - Its "good" counts are a lower bound.
  - Its "bad" counts for a weak system include answers a person would call OK.

## Limits

- **One grader.** No second person graded the same sheet, so there's no person-to-person agreement to compare the judge against.
- **An easy pair.** Shipped vs no-search is mostly good vs bad. This does not show the judge can separate two close versions of the chat, which is the harder case where Sprint 8 found it noisy. Checking that needs two close systems, for example gpt-4o-mini vs gpt-5-mini.
- **Small sample.** 20 turns from 2 courses, answered by gpt-4o-mini.
- **No flagged answers yet.** The plan asked to include answers flagged with the task 2 thumbs-down. None exist yet. The outside tester's flags can be added to a later sheet.
- **Not checked:** the judge's other fields (citation accuracy, faithfulness, abstention).

## Files

- **In this folder (committed):**
  - `human-grades.json`: the hand grades by case and turn, with no course text
  - `agreement-v1-tune.json` and `agreement-v1-report.json`: counts and confusion tables
- **Local only** (`.gitignore`; they quote course text): `answers.json`, `grading.html`, `key.json`, `grades.csv` and `judge-v1.json`.
- **Code:** `backend/scripts/grader_check.py` (sheet, judge and agree commands; the steps are in its docstring), and the `--model` option in `backend/scripts/ask_modes_eval.py`.
