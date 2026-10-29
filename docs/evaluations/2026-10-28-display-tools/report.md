# Display tools: does chat show cards only when it should?

Step 6 of [the generative UI plan](../../plans/2026-10-28-chat-generative-ui.md). Run on 2026-10-29.

**Setup.** `backend/scripts/display_tools_eval.py` sends 21 labelled questions through the shipped `chat.answer` for course 55016 (18-658 Software Requirements and Interaction Design). Search used the real local index (rank fusion only: the reranker model wasn't in this checkout). `show_deadlines` got the real Canvas assignments. `show_quiz` was stubbed so the run didn't write 11 quizzes, but it recorded the options the model asked for. One answer per question, no chat history.

11 questions should show a card (5 deadlines, 6 quiz). The other 10 are near misses: the course's own quizzes and exams ("What's on the midterm exam?", "How many quizzes are there in this course?"), one assignment's content or due date, plain concept questions, and a request to write graded work.

**Models.** gpt-4o-mini (the default) and gpt-4.1, both through OpenAI. The plan asked for a second *provider*, but the Copilot token on this machine had expired (`401 credential expired`). Re-running with `--provider copilot` after signing in again is one command.

## Results

| | gpt-4o-mini | gpt-4.1 |
|---|---|---|
| Card exactly as labelled | **21 / 21** | **21 / 21** |
| Deadlines precision / recall | 1.0 / 1.0 | 1.0 / 1.0 |
| Quiz precision / recall | 1.0 / 1.0 | 1.0 / 1.0 |
| Quiz questions written in the text | 0 | 0 |
| "hard" passed through as difficulty | yes | yes |
| Study panel mentioned without being asked | 0 of 5 | 0 of 5 |
| Study panel mentioned when asked for 15 questions | no | yes |

Raw answers: [openai.json](openai.json) and [openai-gpt-4.1.json](openai-gpt-4.1.json).

## Read by hand

- **Near misses held.** Neither model showed a card for "What's on the midterm exam?", "Are the in-class quizzes graded?", "When is the Heuristic Evaluation due?" or "How many quizzes are there in this course?". These searched and answered with citations instead. "Write my answers for the User Stories in-class deliverable" was refused under the graded-work rule, with no quiz offered in its place.
- **Fixed during this step.** In the first run, gpt-4.1 ended every quiz answer with "If you want more questions, you can generate a longer quiz from the Study panel", even when nobody had asked for more. The tool result now says to mention it only for a request above 5 questions. After the change, gpt-4.1 mentioned it only for the 15-question request, and gpt-4o-mini never did.
- **Known gap.** Asked for 15 questions, gpt-4o-mini says it made "a 5-question practice quiz" without pointing to the Study panel. That's honest about the size, but less helpful. Not worth more prompt for now.
- **Deadline wording.** Once, gpt-4o-mini called a past-due assignment "due soon" (the card itself says "Missing" or shows the date). gpt-4.1's deadline answers were more careful ("the most recent deadline has already passed"). Both still re-state one or two rows in the text, which is fine at this size. The full list is only in the card.
- **Speed.** About 2 s per answer for both models, the same as a plain answer. The quiz itself is written in the background (about 30 s in step 4's live run).

## Not covered

- History-dependent requests ("quiz me on that" after a discussion). `history_note` and the tool's topic description are meant for this, but the set has no multi-turn cases.
- Other courses, and the Copilot provider (above).
