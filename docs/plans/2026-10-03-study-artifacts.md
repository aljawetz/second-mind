# Study artifacts: quizzes and flashcards

Implementation-plan.md Step 11, design spec §8. Sprint 6, due 2026-10-06.

**Decision (2026-10-03):** build both in the app, behaving like NotebookLM's Quiz and Flashcards,
rather than calling NotebookLM. NotebookLM has no public API (the MCP servers drive its private web
endpoints with browser cookies), and using it would send every course file and lecture transcript to
Google, against design spec §5.1 and §6. Mind maps and slides wait for a later sprint.

## What NotebookLM does, and what we copy

Sources: Google's help page (support.google.com/gemininotebook/answer/16958963) and reviews.

| NotebookLM | Here |
| --- | --- |
| Customize: number (Fewer / Standard / More), difficulty (Easy / Medium / Hard), a prompt for the topic | Same three options |
| Uses the notebook's selected sources | Uses the course's indexed material, optionally narrowed to chosen files and sessions |
| Generates in the background | Generates in a background thread; the list shows "Generating…" |
| Quiz: multiple choice, Hint, a short explanation for right and wrong options, Previous / Next | Same |
| Quiz results: score, accuracy, correct, incorrect, skipped; Review answers, Try again | Same |
| Flashcards: flip, Previous / Next, Got it / Missed it, Shuffle, Delete a card, progress remembered | Same |
| Flashcards at the end: practice Same cards, All cards, Only cards you missed | Same |
| Download flashcards as CSV | Same |
| Explain: opens a cited explanation in the chat | Opens a new course chat with the question asked, so the answer is cited like any other |

One addition NotebookLM does not show: every question and card names the passage it was written from
and cites it with the same footnote as chat answers. Anything whose passage does not support it is
dropped before the student sees it (design spec §8: a hallucinated question is worse than none).

## Backend: `backend/study.py`

1. **Material.** Read the course's chunks from its LanceDB table, grouped by document in reading order.
   Narrow to chosen documents if given. If the text is over the budget (about 40k tokens), keep the
   chunks closest to the topic when there is one, else an even spread across documents.
2. **Generate.** One JSON call. Chunks are labelled `c1…cN`; each question or card names its chunk.
   A few more items are asked for than needed, to leave room for step 3.
3. **Check.** In code: drop malformed items, items naming a chunk that wasn't given, and duplicates.
   Shuffle quiz options so the right answer isn't always first. Then one JSON call: is each item
   supported by its chunk? Drop the rest. Keep the counts (generated / unsourced / unsupported): the
   artifact groundedness metric (§12).
4. **Store** under `courses/<id>/study/<artifact_id>.json`, so deleting a course deletes them. Study
   progress (answers, Got it / Missed it, removed cards) is saved in the same file.

Routes: `GET /courses/{id}/study`, `GET /courses/{id}/study/sources`, `POST /courses/{id}/study`,
`GET|DELETE /courses/{id}/study/{aid}`, `POST /courses/{id}/study/{aid}/progress`.

## Frontend

A Study panel above Assignments on course home, like NotebookLM's Studio: Quiz and Flashcards
buttons (each with a pencil for the options) and the list of generated ones. Opening one shows the
quiz or the flashcards full width, with a back link.

## Tests

`tests/test_study.py`, with a scripted model: material selection and budget, validation, dropping
unsupported items, storage and progress, and the routes (in-process server, as in test_ask_memory.py).
Then one live run on a real course, compared against NotebookLM on the same material.

## First live runs (2026-10-03, gpt-4o-mini, course 56350 / 49797)

The whole course (25 documents, 116k characters) fits the budget, so nothing was cut.

| Run | Asked | Written | Dropped by the check | Kept | Time |
| --- | --- | --- | --- | --- | --- |
| Quiz, medium, no topic | 10 | 11 | 0 | 10 | 37 s |
| Flashcards, medium, no topic (before the second round) | 10 | 12 | 5 | 7 | 11 s |
| Quiz, medium, topic "how to do a literature review and research study" | 10 | 14 (2 rounds) | 2 | 10 | 59 s |
| Flashcards, medium, no topic (with the second round) | 10 | 21 (2 rounds) | 10 | 10 | 23 s |

What the dropped items were, read by hand: mostly cards citing the wrong passage (the fact is in
the course, but not where the card says), and a few using outside knowledge ("PICO stands for…" is
not in the cited passage; one card on "positive feedback in student writing" is not in the course at
all). The check let through one quiz question that mixed two documents ("user trust … in AI
interventions for ASD"); its prompt now rejects items that bring in a subject the passage doesn't
discuss.

Without a topic, questions lean on whatever is longest (a sample project proposal and a sample
literature review). With a topic they stay on it. For the demo, give a topic or choose sources.

Still to do: grade a fixed set by hand (is each kept item answerable from its passage, and is it a
good study question), the same material in NotebookLM for comparison, and the same runs with a
stronger model.
