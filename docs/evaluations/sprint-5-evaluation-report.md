# Sprint 5 evaluation report: how Second Mind answers questions

Date: 2026-09-26
Full working report: [2026-09-23-ask-modes/report.md](2026-09-23-ask-modes/report.md)
Script: `backend/scripts/ask_modes_eval.py` (`--set first` or `--set heldout`)
Grades: `heldout-grades.json`, `shipped-grades.json`, `reindexed-grades.json` in the folder above. Raw answers are not in git because they quote course material, including staff names and emails. Rerun the script to regenerate them.

## Summary

We compared the old chat (baseline) against three designs where the model decides when to search, and shipped the best one. On 67 questions across three real courses, the shipped chat gave 28 good answers on the first set (of 34) and 29 on the held-out set (of 33), against 21 and 21 for the baseline. It handles follow-up questions (13 of 14 right in every run) where the baseline handled 3 of 14. A later indexing fix raised the first set to 32 good and 0 bad.

This is small, hand-graded evidence from one model. It shows clear patterns, not exact percentages. We did not measure retrieval precision@k or a formal citation groundedness score, which the design spec (§12) names as the target metrics. See "Limits".

## What we tested

Every option used gpt-4o-mini and the same course search.

| Option | How it works |
|---|---|
| **A. Old chat (baseline)** | Each question goes straight to course search. No memory of the conversation. |
| **B. Search tool, course only** | The model sees the whole chat, decides what to search, and may only use course materials. |
| **C. Search tool + own knowledge** | Same as B, but it may use its own knowledge under a "General knowledge" label. |
| **D. Stricter C** | C with extra rules: always search, cite only what a source says, label all general knowledge. |
| **Shipped chat** | D built into the app (`backend/chat.py`), with the fixes from this evaluation. |

**Questions.** First set: 27 chats (34 questions) on 18-654 Software Testing & Operations. Held-out set: 26 chats (33 questions) on 18-654, 18-658 Software Requirements and Interaction Design, and Advanced AI for Industry & Society. Groups: course facts, concepts the course teaches, concepts not in the materials, trick questions (for example an assignment that doesn't exist), study help, and follow-up chats.

**Grading.** Each answer was checked against the actual course materials as Good (correct, useful, sources make sense), OK (not wrong but unhelpful or unlabeled) or Bad (wrong, made up, or failed to answer something it should have). On the held-out set, the four answers to each question were shuffled under random letters and all grades were saved before the letters were matched back.

## Results

| | A. Baseline | B | C | D | Shipped |
|---|---|---|---|---|---|
| Good, first set (of 34) | 21 | 26 | 28 | 30 | 28 |
| Good, held-out set (of 33) | 21 | 22 | 20 | 24 | 29 |
| Bad, first set | 9 | 5 | 2 | 2 | not recorded |
| Bad, held-out set | 6 | 5 | 6 | 6 | not recorded |
| Follow-ups right, first set (of 7) | 1 | 6 | 4 | 4 | not run |
| Follow-ups right, held-out set (of 7) | 2 | 5 | 3 | 5 | not run |
| Answers citing a source that doesn't say that, first set | 0 | 2 | 2 | 0 | not recorded |
| Time for a full answer | 1.5 s | 3.3 s | 3.3 s | 3.1 s | not recorded |
| Cost per question | $0.0003 | $0.0004 | $0.0004 | $0.0004 | not recorded |

The shipped chat answered 13 of 14 follow-ups correctly in each of 3 runs.

After the indexing fix (OCR was overwriting correct PDF text, and the syllabus grading table sat past the embedding model's 512-token window), re-graded blind against the previous run:

| | Before | After |
|---|---|---|
| Good, first set (of 34) | 29 | 32 |
| Bad, first set | 4 | 0 |
| Good, held-out set (of 33) | 29 | 28 |

The one held-out loss is a page whose similarity score moved from about 0.52 to 0.494, just under the 0.5 cutoff.

## What we found

1. **The baseline cannot handle follow-ups.** It searches for the follow-up's exact words. "And the final?" returned Java's `final` keyword, and "Explain the second one." explained a search result instead of the earlier answer. Tool-based options understood both.
2. **"Only use course materials" is not a rule the model follows.** Option B still explained mutation testing from its own knowledge and attached citations to slides that don't mention it (3 of 3 runs). A made-up answer with a real-looking citation is worse than no answer.
3. **Strict labeling works.** Option D kept general knowledge under a clear label on every "not in the materials" question and said "not found" for grading weights instead of inventing them.
4. **Search matters more than chat style.** On the held-out courses, similarity scores bunch between about 0.47 and 0.6, so small wording changes decided whether anything was found. The shipped chat always searches the student's own words first, and the model must also search in its own words on follow-ups.
5. **Part of the held-out gap was a bug in our evaluation.** Options B, C and D were shown only the first 1,500 characters of each result, while the baseline saw whole chunks. The shipped chat sends whole chunks, and those misses went away.

## Failures and limitations

- **Source text errors hit every option.** The grading rubric slide is a chart, and only "12.5%" and "17.5%" survived without their labels. "2nd" was read as `2"4`, so the final exam became "December 24". The indexing fix addressed these, and "Which part is worth the most?" now gets the real weights 3 of 3 times.
- **Citation format broke in option D** (15 of 34 answers on the first set, 7 of 33 on the held-out set). The shipped chat checks and renumbers citations in code, and no broken formats appeared.
- **The 0.5 cutoff was tuned on one course.** At 0.4 the shipped chat gave the same number of good answers and one more made-up fact, so it stays at 0.5. It should be re-tuned across courses.
- **Made-up facts were not eliminated.** On the held-out set each tool option stated 2 wrong course facts and the baseline 1. An example is listing "Class #2 topics" from an overview slide when the Class #2 recording is one sentence.
- **Latency.** Tool options take about 2 seconds longer for a full answer (3.1 to 3.3 s versus 1.5 s), because the model first decides what to search.

## Limits of this evidence

- **Not the spec's metrics.** We graded answers Good, OK or Bad. We did not compute retrieval precision@k or a citation groundedness score. The Sprint 4 smoke test (4 known-answer queries, all correct in the top 3) is the only precision-style check so far.
- **The baseline is the old chat, not the Sprint 3 baseline.** Sprint 3 measured text extraction only (an 11-page PDF gave 1,614 characters as plain text and 4,980 with OCR). The old chat is the fair comparison for this question, and the indexing fix builds on the Sprint 3 finding that extraction quality drives answer quality.
- **Small and single-run.** 33 to 34 questions per set, one model (gpt-4o-mini), most questions run once. On the held-out set D's lead over the baseline was 3 answers, which could be luck.
- **Grader bias.** Claude wrote the questions and graded the answers. The raw answers were kept locally so any grade can be checked.
- **The held-out set is no longer clean.** The shipped chat's fixes came partly from failures on the held-out questions, so its 29 is not a fresh test. The first-set count shipped at 28 and was later re-graded at 29, one call apart, on the same answers.
- **Model.** A stronger model might follow the citation and labeling rules better, at a higher cost.

## Before end-to-end integration

1. Add precision@k and citation groundedness to `ask_modes_eval.py`, so the sprint's stated metrics exist.
2. Re-tune the similarity cutoff across all courses, or show the model the top results with their scores.
3. Write a fresh question set on unseen courses and rerun all options, since the current held-out set has been used to tune the shipped chat.
4. Show course facts and general knowledge differently in the app, so the label doesn't depend on the model writing it.
5. Update design spec §7, which still says the chat must never use outside knowledge.
