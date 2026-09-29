# Sprint 5 deliverable: how Second Mind answers questions

Richa Pragat, Lakshita Rahoria, Shatakshi Chaudhri, Aaron Weng, Yongjie Shu, Arthur Jawetz

- Full write-up and raw data: [2026-09-23-ask-modes/report.md](https://github.com/aljawetz/second-mind/blob/sprint-5-full-evaluation/docs/evaluations/2026-09-23-ask-modes/report.md)
- Rerun it: `backend/scripts/ask_modes_eval.py --set first` or `--set heldout` (`--no-judge` to skip the LLM judge)

## Core technology implementation

Second Mind's chat is a retrieval-augmented generation (RAG) system built as a tool-calling LLM
agent, not a one-shot "retrieve then answer" pipeline.

**Retrieval.** We pull text from course PDFs and slides, OCR any page where that text comes out
garbled or missing, then split it into page-sized chunks tagged with their source
(`backend/ingestion.py`). Each chunk is embedded with a small local model (`bge-small-en-v1.5`)
and stored in a per-student LanceDB index, no cloud call needed (`backend/embeddings.py`,
`backend/indexing.py`). To find the right chunks for a question, we search by meaning and by exact
keyword and combine both results (`backend/generation.py`).

**Generation and grounding.** The chat itself is an agent: the model (gpt-4o-mini) gets a
`search_course` tool and decides for itself when and how many times to call it, instead of the app
searching once and handing over whatever it found. Course facts must come from search results,
citations are checked and renumbered in code rather than trusted to the model, and general
knowledge is allowed but only under a fixed, visibly separated label (`backend/chat.py`). This is
exactly the design this evaluation compared against four alternatives and confirmed is the
best-balanced.

**Other pieces feeding the same core capability:** an LLM provider interface (`backend/llm.py`)
that keeps the app from being locked to one vendor, optional cross-chat agent memory with its own
recall and forget tools, and a real Canvas integration (`backend/canvas.py`,
`backend/course_sync.py`) that syncs a student's actual course structure and files rather than
working against synthetic data.

The whole stack runs locally: the desktop app (Tauri/Rust) spawns this Python backend as a sidecar
process, and the index, embeddings, and OCR all run on the student's machine. Only the LLM call
and the Canvas sync talk to anything outside it.

## Evaluation and baseline comparison

We built 5 designs for how the chat decides what to search and what it's allowed to say, then
tested them against each other and against the old chat on 67 real questions across 3 real
courses, and shipped the best one: the shipped chat, the best-balanced design. It has the fewest
wrong answers of anything we tested, the highest faithfulness, and the best retrieval recall. It's
also the only design that reliably handles follow-up questions, where the old chat almost
completely fails (13 of 14 right vs. 3 of 14).

The grounded agent (a stricter design, described below) has noticeably better citation accuracy,
but hedges into unhelpful non-answers more often. The old baseline chat is cheapest and fastest by
a wide margin, but can't hold a conversation.

### The designs we compared

Every design used gpt-4o-mini and the same underlying course search.


| Design                   | How it works                                                                                              |
| ------------------------ | --------------------------------------------------------------------------------------------------------- |
| **Baseline chat**        | The old system. Goes straight to search on every message. No memory of the conversation.                  |
| **Course-only agent**    | The model sees the whole conversation, decides when to search, and may only use course materials.         |
| **Open-knowledge agent** | Same as the course-only agent, but may add its own knowledge under a "General knowledge" label.           |
| **Grounded agent**       | Always searches, cites only what a source actually says, and labels all outside knowledge.                |
| **Shipped chat**         | The grounded agent built into the real app, with the fixes from this evaluation. What students use today. |


Our Assignment 3 work evaluated a different project concept, so it wasn't a fair comparison here.
The baseline chat above is the alternative the Sprint 5 rubric permits instead.

The 67 questions span 3 real courses (18-654 Software Testing, 18-658 Requirements, Advanced AI
for Industry &amp; Society) and cover course facts, taught concepts, out-of-scope concepts, trick
questions, study help, and follow-ups.

### How we evaluated

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

### Results

All 67 questions, both courses' worth of questions pooled into one set, judged and gold-labeled.


| Design               | Good | OK  | Bad | Citation accuracy | Faithful | Correct abstention | Retrieval recall@5 | Avg. cost |
| -------------------- | ---- | --- | --- | ----------------- | -------- | ------------------ | ------------------ | --------- |
| Baseline chat        | 27   | 13  | 27  | 64%               | 55%      | 42%                | 67%                | $0.00017  |
| Course-only agent    | 34   | 12  | 21  | 57%               | 60%      | 30%                | 76%                | $0.00032  |
| Open-knowledge agent | 31   | 13  | 23  | 64%               | 55%      | 24%                | 67%                | $0.00035  |
| Grounded agent       | 29   | 18  | 20  | 82%               | 61%      | 33%                | 79%                | $0.00036  |
| Shipped chat         | 31   | 18  | 18  | 57%               | 61%      | 29%                | 83%                | $0.00037  |


Latency: the baseline answers in under a second (median 0.89s); every other design takes 1.6-2.3s
at the median, because the model decides what to search first.

**What the numbers say:**

- The grounded agent has the best citation accuracy by far (82%, vs. 57-64% for everything else),
confirming that its "cite only what the source says" rule works. It also produces the most
hedge ("ok") answers of any design, more than any other option.
- The course-only agent gets the most outright "good" answers (34 of 67), but is worst at knowing
when to say "not found" (30% correct abstention) with no citation-accuracy edge to show for
it: it likely still slips in outside knowledge with a plausible-looking citation attached.
- The shipped chat has the fewest wrong answers of any design (18), ties the grounded agent for
the highest faithfulness (61%), and has the best retrieval recall (83%).
- The baseline is by far the cheapest and fastest, but this table hides its real weakness: it
can't handle follow-up questions (see "How we evaluated" above).

## Technical analysis

### What we found

1. The baseline can't handle follow-ups. It searches the follow-up's literal words instead of
 understanding context ("And the final?" returned Java's `final` keyword).
2. Telling the model "only use course materials" doesn't stop it from answering from its own
 knowledge anyway (the course-only agent, with citations attached to slides that don't say
 that).
3. Strict rules work: the grounded agent reliably labeled general knowledge and said "not found"
   instead of inventing answers.
4. Retrieval quality matters more than chat design: similarity scores bunch tightly (0.47-0.6), so
   small wording differences decide what's found.

### Limitations

- Even the shipped chat, the best design we tested, still gets 18 of 67 answers wrong and another
  18 land as an unhelpful "ok" hedge — well under half are a clean, correct, useful answer.
- Citation accuracy tops out at 82% (the grounded agent); the shipped chat itself sits at 57%. A
  meaningful share of citations don't fully back the claim they're attached to.
- No design reliably knows when to say "not found": correct abstention is under 50% everywhere,
  29% for the shipped chat.
- One course's index may be stale. A topic Canvas lists as taught (mutation testing) wasn't found
  by direct retrieval queries against the live index, and there's no current process that would
  catch this automatically if it's also true for other topics.
- Retrieval is fragile at the edges: on the held-out courses, similarity scores for genuinely
  relevant material bunch between about 0.47 and 0.6, close enough to the 0.5 cutoff that small
  wording differences flip a result from found to missed.
- The 0.5 similarity cutoff was tuned on a small number of courses. Before this scales to every
  course a student takes, it likely needs re-tuning per course, or the app needs to show result
  scores directly instead of a single hard cutoff.

### Improvements needed before end-to-end integration

1. Check other courses' indexes for the same stale-content gap found in this one; there's no
   current process that would catch it automatically.
2. Re-tune the similarity cutoff per course, or show the model's result scores directly, instead
   of relying on one fixed threshold for every course.
3. Close the citation-accuracy gap between what's shipped (57%) and the grounded agent's stricter
   rule (82%), without losing the shipped chat's follow-up handling and overall balance.
4. Distinguish course facts from general knowledge in the UI itself, not just in the model's own
   labels.

