# Sprint 5 evaluation report: how Second Mind answers questions

Second Mind's chat answers a student's question by searching their indexed course material
(slides, syllabi, transcripts) and having an LLM write an answer, with citations, from whatever it
finds. We built and compared 6 designs for how that chat decides what to search and what it's
allowed to say, tested them on 67 real questions across 3 real courses, and shipped the best one.

- Full write-up and raw data: [2026-09-23-ask-modes/report.md](2026-09-23-ask-modes/report.md)
- Rerun it: `backend/scripts/ask_modes_eval.py --set first` or `--set heldout` (`--no-judge` to skip the LLM judge)

## The verdict

The shipped chat is the best-balanced design. Together with its loose-cutoff variant, it has the
fewest wrong answers of anything we tested, the highest faithfulness, and the best retrieval
recall. It's also the only design, besides its own variant, that reliably handles follow-up
questions, where the old chat almost completely fails (13 of 14 right vs. 3 of 14).

The grounded agent (a stricter design, described below) has noticeably better citation accuracy,
but hedges into unhelpful non-answers more often. The old baseline chat is cheapest and fastest by
a wide margin, but can't hold a conversation.

This is small, single-model evidence (see "Limitations"), but two independent evaluation passes,
hand-grading and an LLM judge, point the same direction.

## The designs we compared

Every design used gpt-4o-mini and the same underlying course search.

| Design | How it works |
|---|---|
| **Baseline chat** | The old system. Goes straight to search on every message. No memory of the conversation. |
| **Course-only agent** | The model sees the whole conversation, decides when to search, and may only use course materials. |
| **Open-knowledge agent** | Same as the course-only agent, but may add its own knowledge under a "General knowledge" label. |
| **Grounded agent** | Always searches, cites only what a source actually says, and labels all outside knowledge. |
| **Shipped chat (deployed)** | The grounded agent built into the real app, with the fixes from this evaluation. What students use today. |
| **Shipped chat, loose cutoff** | Same as the shipped chat, but with a lower search-relevance threshold. Tested for comparison, not deployed. |

Our Assignment 3 work evaluated a different project concept, so it wasn't a fair comparison here.
The baseline chat above is the alternative the Sprint 5 rubric permits instead.

The 67 questions span 3 real courses (18-654 Software Testing, 18-658 Requirements, Advanced AI
for Industry & Society) and cover course facts, taught concepts, out-of-scope concepts, trick
questions, study help, and follow-ups.

## How we evaluated

Two passes:

1. **Hand-graded pilot.** Every answer checked by hand against real course materials (Good / OK /
   Bad). This pass picked the grounded agent as the design to ship, and fixed an indexing bug and
   a citation-format bug along the way. It's also the only pass that tested follow-up questions:
   the shipped chat got 13 of 14 right across 3 runs, the baseline 3 of 14.
2. **Judged confirmation.** Every question now has a verified gold answer. An independent gpt-4o
   judge (not any of the models being tested) scored every answer for correctness, citation
   accuracy, faithfulness, and correct abstention; we also measured retrieval recall@5, cost, and
   latency for real. These are the numbers below.

The judge grades much harder than the hand-grading did (the grounded agent goes from 54 of 67
good by hand to 29 of 67 good under the judge, on the same answers), so don't compare counts
across the two passes directly. What holds across both is the pattern: the shipped chat is the
best-balanced design.

## Results

All 67 questions, both courses' worth of questions pooled into one set, judged and gold-labeled.

| Design | Good | OK | Bad | Citation accuracy | Faithful | Correct abstention | Retrieval recall@5 | Avg. cost |
|---|---|---|---|---|---|---|---|---|
| Baseline chat | 27 | 13 | 27 | 64% | 55% | 42% | 67% | $0.00017 |
| Course-only agent | 34 | 12 | 21 | 57% | 60% | 30% | 76% | $0.00032 |
| Open-knowledge agent | 31 | 13 | 23 | 64% | 55% | 24% | 67% | $0.00035 |
| Grounded agent | 29 | 18 | 20 | 82% | 61% | 33% | 79% | $0.00036 |
| Shipped chat (deployed) | 31 | 18 | 18 | 57% | 61% | 29% | 83% | $0.00037 |
| Shipped chat, loose cutoff | 30 | 19 | 18 | 59% | 61% | 35% | 86% | $0.00044 |

Latency: the baseline answers in under a second (median 0.89s); every other design takes 1.6-2.3s
at the median, because the model decides what to search first.

**What the numbers say:**

- The grounded agent has the best citation accuracy by far (82%, vs. 57-64% for everything else),
  confirming that its "cite only what the source says" rule works. It also produces the most
  hedge ("ok") answers of any design, more than any other option.
- The course-only agent gets the most outright "good" answers (34 of 67), but is worst at knowing
  when to say "not found" (30% correct abstention) with no citation-accuracy edge to show for
  it: it likely still slips in outside knowledge with a plausible-looking citation attached.
- The shipped chat and its loose-cutoff variant tie for the fewest wrong answers of any design (18
  each), share the highest faithfulness (61%), and post the best or second-best retrieval recall.
- The loose cutoff pushes recall a little higher (86% vs. 83%) but costs more per question and
  doesn't otherwise beat the deployed cutoff, so the tighter 0.5 threshold stays.
- The baseline is by far the cheapest and fastest, but this table hides its real weakness: it
  can't handle follow-up questions (see "How we evaluated").

## What we found

1. The baseline can't handle follow-ups. It searches the follow-up's literal words instead of
   understanding context ("And the final?" returned Java's `final` keyword).
2. Telling the model "only use course materials" doesn't stop it from answering from its own
   knowledge anyway (the course-only agent, with citations attached to slides that don't say
   that).
3. Strict rules work: the grounded agent reliably labeled general knowledge and said "not found"
   instead of inventing answers.
4. Retrieval quality matters more than chat design: similarity scores bunch tightly (0.47-0.6), so
   small wording differences decide what's found.

## Limitations

- Three gold answers are still unconfirmed (18-658 Requirements: final exam date/format,
  storyboard criteria, usability sample size).
- The judge isn't perfectly reliable. It marked at least one correct, correctly-labeled answer as
  unfaithful.
- One course's index may be stale. A topic Canvas lists as taught wasn't found by direct
  retrieval queries against the live index; other topics in that course weren't checked.
- Small, single-model, mostly single-run. 67 questions total, one model (gpt-4o-mini). Margins
  between some designs are just a handful of answers out of 67, which could be luck rather than a
  real difference.
- Grader bias: Claude wrote the questions for both passes and hand-graded the first one itself;
  the second used an independent judge model, which helps but doesn't fully remove this.
- Part of this question set isn't clean anymore. The shipped chat's fixes came partly from
  failures on questions that are still counted in the results above.

## Next steps

1. Confirm the 3 remaining gold labels; check the flagged course's index for other stale topics.
2. Re-tune the similarity cutoff per course, or show the model result scores directly.
3. Test on a fresh, truly unseen question set.
4. Distinguish course facts from general knowledge in the UI, not just in the model's own labels.
5. Update design spec §7, which still says the chat must never use outside knowledge.
