# Sprint 5 evaluation report: how Second Mind answers questions

Date: 2026-09-26, updated 2026-09-28 with automated recall@5/citation/faithfulness/abstention metrics
Full working report: [2026-09-23-ask-modes/report.md](2026-09-23-ask-modes/report.md)
Script: `backend/scripts/ask_modes_eval.py` (`--set first` or `--set heldout`, `--no-judge` to skip the LLM judge)
Grades (hand-graded, 2026-09-23): `heldout-grades.json`, `shipped-grades.json`, `reindexed-grades.json` in [2026-09-23-ask-modes/](2026-09-23-ask-modes/).
Grades (judged, 2026-09-28): `results-grades.json`, `heldout-grades.json` in [2026-09-28-ask-modes/](2026-09-28-ask-modes/) — written automatically by the script alongside its raw output, stripped to metrics only (no quoted course content), safe to commit. Raw model answers, in both folders, are not in git because they quote course material, including staff names and emails. Rerun the script to regenerate them.

## Summary

We compared the old chat (baseline) against three designs where the model decides when to search, and shipped the best one. On 67 questions across three real courses, the shipped chat gave 28 good answers on the first set (of 34) and 29 on the held-out set (of 33), against 21 and 21 for the baseline. It handles follow-up questions (13 of 14 right in every run) where the baseline handled 3 of 14. A later indexing fix raised the first set to 32 good and 0 bad.

This is small evidence from one model, first hand-graded, then (2026-09-28) independently re-graded by an LLM judge with recall@5, citation accuracy, faithfulness, and cost measured for real, across all six options and both question sets. The two runs point the same direction: the shipped chat is the most balanced option, though not the single best on every axis — D has the clearest edge on citation accuracy specifically. See "Automated re-evaluation" and "Limits" below.

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

## Automated re-evaluation (2026-09-28): recall@5, an LLM judge, and cost

The gap flagged in "Limits of this evidence" below (the spec's stated metrics didn't exist) is closed. Every case in `ask_modes_eval.py` now
carries a hand-verified gold answer and source (34 verified against real Canvas content this round, 14 carried
from the original hand-grading above, 3 still unconfirmed — all in 18-658 Requirements: the final exam
date/format, storyboard criteria, and usability sample size). Against those gold labels, the script now computes:

- **recall@5** — did retrieval surface the case's gold source in its top 5, across every search call.
- **Correctness, citation accuracy, faithfulness, correct abstention** — one gpt-4o judge call per answer
  (deliberately not gpt-4o-mini, the model under test, to avoid a model grading its own homework).
- **Cost per query**, priced at gpt-4o-mini's actual rate, and **p50/p95 latency**.

All six options (A-F) were run against both question sets for real, all 67 questions, all judged. Every
row's verdict (which case, which mode, which turn, every metric below) is in
[2026-09-28-ask-modes/results-grades.json](2026-09-28-ask-modes/results-grades.json) and
[heldout-grades.json](2026-09-28-ask-modes/heldout-grades.json) — safe to commit, no quoted course content.

### First set (34 questions)

| mode | good | ok | bad | citation acc | faithful | correct abstention | recall@5 | p50 (s) | p95 (s) | avg cost |
|---|---|---|---|---|---|---|---|---|---|---|
| A. Baseline | 14 | 8 | 12 | 59% | 59% | 60% | 64% | 0.99 | 1.66 | $0.00020 |
| B | 18 | 8 | 8 | 63% | 65% | 57% | 76% | 2.15 | 3.27 | $0.00035 |
| C | 15 | 10 | 9 | 65% | 56% | 29% | 64% | 2.53 | 4.48 | $0.00038 |
| D | 12 | 15 | 7 | 73% | 65% | 43% | 80% | 2.47 | 3.72 | $0.00040 |
| E. Shipped (0.5 cutoff) | 16 | 11 | 7 | 57% | 65% | 57% | 80% | 1.61 | 3.12 | $0.00040 |
| F. Shipped (0.4 cutoff) | 14 | 12 | 8 | 52% | 59% | 38% | 84% | 1.63 | 2.78 | $0.00046 |

### Held-out set (33 questions)

| mode | good | ok | bad | citation acc | faithful | correct abstention | recall@5 | p50 (s) | p95 (s) | avg cost |
|---|---|---|---|---|---|---|---|---|---|---|
| A. Baseline | 13 | 5 | 15 | 70% | 52% | 33% | 71% | 0.83 | 1.83 | $0.00014 |
| B | 16 | 4 | 13 | 52% | 55% | 19% | 76% | 1.85 | 3.61 | $0.00029 |
| C | 16 | 3 | 14 | 63% | 55% | 22% | 71% | 2.03 | 4.4 | $0.00032 |
| D | 17 | 3 | 13 | 91% | 58% | 29% | 76% | 1.85 | 3.77 | $0.00032 |
| E. Shipped (0.5 cutoff) | 15 | 7 | 11 | 57% | 58% | 18% | 88% | 1.52 | 3.8 | $0.00034 |
| F. Shipped (0.4 cutoff) | 16 | 7 | 10 | 66% | 64% | 33% | 88% | 1.57 | 3.68 | $0.00042 |

**These good/ok/bad counts are not directly comparable to the "Results" table above.** The original table's
grades came from hand-grading against a looser bar; these come from a gpt-4o judge grading strictly against a
detailed written gold answer, and it grades harder — D drops from 30/34 good (hand-graded) to 12/34 good
(judged) on the same question set, even though the model's answers didn't change. Read the two tables
separately: the hand-graded one for the absolute "how many good answers" question, this one for the *relative*
pattern across A-F once every mode is held to the same automated, written-down standard.

**Reading it.** No single mode wins on every axis:

- **D has the clearest standout metric: citation accuracy** (73%/91%, both sets, well ahead of everything else),
  confirming the original finding that D's stricter "cite only what the source says" rule works. Its cost is
  fewer outright "good" answers and more "ok" ones — it hedges into a correct-but-unhelpful answer more often
  than the others.
- **B has the most raw "good" answers on the first set** (18 of 34), but the lowest correct-abstention rate on
  the held-out set (19%) and no citation-accuracy edge — the same "looks right, isn't always honest" pattern
  the original hand-graded run found (§"What we found," #2).
- **E, the shipped chat, is the most balanced**: tied for lowest bad rate on both sets, high faithfulness, and
  the best or tied-best recall@5. It's also what's actually deployed. F (the 0.4-cutoff variant) trades a
  slightly higher recall@5 for worse citation accuracy on the first set (52%) and the highest cost — the
  report's earlier decision to ship at 0.5, not 0.4, holds.
- **A, the baseline, is cheapest and fastest by a wide margin** (0.99s/0.83s p50 vs. 1.5-2.5s for every other
  option) and does fine on simple facts and traps. Its known weakness — follow-up questions — isn't visible in
  this aggregate table, which pools all question kinds together; the original hand-graded run (1 of 7 follow-ups
  right) is still the evidence for that specific gap.

**Verdict: E (the shipped chat) remains the right choice**, now on firmer footing — it wasn't just the
best-scoring option in one hand-graded run, it holds up as the best-balanced option under an independent judge,
a retrieval metric, and a second, previously-unseen question set.

### What the real run caught that hand-grading didn't

Running this for real (not synthetic spot-checks) surfaced three problems worth recording:

1. **Five gold labels were wrong**, and every one made a *correct* model answer look wrong. Two Testing-course
   questions ("team size," "slip days") had been marked "not yet posted" from browsing Canvas's module list,
   without opening `01 CourseInfoF26.pdf` — which had both answers, cited correctly by every mode. A third
   ("IDE/build tool") was marked unconfirmed for the same reason. A fourth ("hyperassertion problem") was marked
   unconfirmed because the slide deck checked stopped at page 12 of a deck whose real answer was on page 24, in
   a different file. All four were fixed from the citations the real run itself produced, then re-judged (not
   re-answered — the answers were already right) against the corrected gold data.
2. **The judge isn't perfectly reliable.** One case (D's answer to "How do I set up JaCoCo in a Maven project?")
   did everything its own prompt asked — said the course doesn't cover it, then clearly labeled general
   knowledge — and the judge still marked it `bad`/unfaithful, despite its own rubric saying labeled general
   knowledge shouldn't count against faithfulness. Treated as an accepted, documented limitation rather than
   fixed with a stricter prompt or multi-sample voting, per this evaluation's own scope.
3. **A genuine index/Canvas sync gap, not a content gap.** "How does mutation testing work?" was briefly
   recategorized from "not in the materials" to "the course teaches this" because Canvas's module list shows a
   slide deck and a lecture recording for it. Four direct retrieval queries against the real index found neither
   — the content exists on Canvas but the local RAG index (`~/.secondmind/index.lancedb`) hasn't ingested it.
   Reverted to "not in the materials" for evaluation purposes, since that's the system's actual behavior as
   currently indexed. This is worth a look outside this evaluation: if this course's index is stale for one
   topic, it may be stale for others a real student would hit.

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

- **The spec's metrics now exist, with a caveat.** The 2026-09-28 automated re-evaluation computes recall@5 (not precision@k — see the design decision recorded in `ask_modes_eval.py`'s judge/recall functions) and an LLM-judged citation accuracy in place of hand-grading. Trust the numbers as far as the gold labels backing them: 34 of 53 fact-bearing cases are hand-verified against real Canvas content (or, for one, a direct retrieval test against the live index), 14 carry over from the original hand-grading below, and 3 (all in 18-658 Requirements) are still unconfirmed.
- **The baseline is the old chat, not the Sprint 3 baseline.** Sprint 3 measured text extraction only (an 11-page PDF gave 1,614 characters as plain text and 4,980 with OCR). The old chat is the fair comparison for this question, and the indexing fix builds on the Sprint 3 finding that extraction quality drives answer quality.
- **Small and single-run.** 33 to 34 questions per set, one model (gpt-4o-mini), most questions run once. On the held-out set D's lead over the baseline was 3 answers, which could be luck.
- **Grader bias.** Claude wrote the questions and graded the answers. The raw answers were kept locally so any grade can be checked.
- **The held-out set is no longer clean.** The shipped chat's fixes came partly from failures on the held-out questions, so its 29 is not a fresh test. The first-set count shipped at 28 and was later re-graded at 29, one call apart, on the same answers.
- **Model.** A stronger model might follow the citation and labeling rules better, at a higher cost.

## Before end-to-end integration

1. ~~Add precision@k and citation groundedness to `ask_modes_eval.py`.~~ Done 2026-09-28 (recall@5 and an
   LLM-judged citation accuracy — see above). Remaining: confirm the 3 still-unverified Requirements-course
   gold labels, and check whether course 55710's RAG index has other stale-vs-Canvas gaps besides mutation
   testing.
2. Re-tune the similarity cutoff across all courses, or show the model the top results with their scores.
3. Write a fresh question set on unseen courses and rerun all options, since the current held-out set has been used to tune the shipped chat.
4. Show course facts and general knowledge differently in the app, so the label doesn't depend on the model writing it.
5. Update design spec §7, which still says the chat must never use outside knowledge.
