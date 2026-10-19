# Sprint 7 team task benchmark: protocol

Four teammates (P1 to P4) each answer questions about course 49797 (Advanced AI, indexed here as 56350) in two ways: with Second Mind, and the way students work today (Canvas alone). Record everything in [benchmark.csv](benchmark.csv). The plain-chatbot baseline is already measured automatically (mode G in [results.md](results.md)).

Teammates are not independent users. The report calls this a controlled pilot.

## Before anyone is timed (one person, 20 minutes)

1. **Ground truth: done Oct 18.** The answers are in `benchmark-key.md` (kept local), confirmed in Canvas. One check remains: open the syllabus PDF (CMUiii_Syllabus_..._v2.pdf) and confirm it has no final exam and no textbook, since T3 depends on that.
2. **Stale "not posted" questions: replaced.** The Sprint 3 deadline and the LLM certificate both exist in Canvas now, so they were swapped for X1 and X2.
3. **Sync the app** so the index is current, and check Second Mind can answer at least one of the six (so a failed sync is not scored as a failure of the tool).

## Tasks

Each task is a pair of questions of the same kind. Everyone answers one question from each pair with Second Mind and the other with Canvas alone, so nobody sees the same fact twice.

| Task | Pair (question ids from `ask_modes_eval.py`) | What it tests |
| --- | --- | --- |
| T1 | H12 "How many students can be on a project team?" / H14 "How recent should the papers in my literature search be?" | Finding a course rule |
| T2 | H13 "Which citation style should I pick in Zotero?" / H11 "What are the Big Four AI conferences according to the course?" | Finding a fact inside a file |
| T3 | X1 "When is the final exam?" / X2 "Which textbook do I need to buy?" | Telling that something is not in the course |

`benchmark.csv` already assigns, per person, which question goes with which condition and in what order (counterbalanced so order and question difficulty do not line up with the tool).

## Running a trial

- Timer starts when the person reads the question aloud, stops when they say "answer" and state it.
- 5 minute cap. If they hit the cap, record 300 and mark incorrect.
- Canvas alone: no AI tools, no asking anyone. Second Mind: the app only.
- Record `answer_given`, `correct` against the key, and `source_found` (y/n: could they point to where it came from).
- Do not coach. Note anything odd in `notes` (for example, the app was slow, or the answer was right but uncited).

## Other measured pieces

- **Quiz audit (hand-grading).** Two or three people each take [quiz-audit-sheet.csv](quiz-audit-sheet.csv) (kept local). Answer the question first with no material (column "your answer without material"), then read the passage and mark answerable and guessable. Only afterwards compare with `quiz-audit-key.csv`. Report the share answered correctly blind against the 25% chance level. Do not compare with the model's no-passage score; a model's background knowledge says nothing about how hard the quiz is for a student. If time allows, have one person who has studied the topic and one who has not take the same 10 questions, to see whether the score separates them.
- **Judge check.** Hand-grade 10 shipped-chat answers from `results.json` (good, ok, bad) and report how often you agree with the judge. Include the five "not posted" answers.
- **Lecture capture.** One person reads a 3-minute script containing five one-line clarifications ("the quiz moved to Thursday", and similar) into the app's session recorder. Ask five questions about the clarifications afterwards and report how many the app recovers, plus a word error rate on a slice of the transcript. Baseline: those details are otherwise lost.

## What to compute

For each task: median seconds and share correct by condition; share with source found. Report n (4 people) and the spread, not just the medians.
