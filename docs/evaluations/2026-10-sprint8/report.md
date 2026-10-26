# Sprint 8 report: robustness and responsible deployment

Second Mind, search and chat. All numbers come from the files in `docs/evaluations/2026-10-sprint8/final/`. 536 tests pass.

Sprint 8 made the chat better at finding the right course material, tested it against odd input, failures and load, and added protections for students. On 60 answerable questions, the new search finds 45 of the right facts, up from 36. The right result now comes first far more often. The chat handles every odd input we tried without crashing, and it says "I couldn't find it" when the course does not cover a question.

## 1. Evidence-driven system improvement

### 1.1 What we improved and why

Sprint 7 (three student interviews, a live demo and a 25-question benchmark) showed that students could not rely on the chat to find the right page. Two findings drove this sprint: search missed relevant material, and it returned too many irrelevant passages. Students also ask about dates ("what is due next week?"), which the chat could not answer.

We made three changes:

1. **Better search.** Results from meaning search and keyword search are now merged by rank, not by raw score. A small local model then re-sorts the top 20 results so the best five come first.
2. **Date awareness.** The chat knows today's date. Searches with "today", "tomorrow", "this week" or "next week" get the real dates added, because course pages say "Due Wed, Oct 28, 2026" and never "next week".
3. **A way to measure it.** Search is scored without calling a model. Each question is searched once, and a result counts as correct if its text contains a fact we wrote down from the course. Matching file names do not count.

### 1.2 Before and after

Over all 60 answerable questions (13 development, 19 test, 28 chat):

| | Before: merged by score | After: merged by rank, then re-sorted |
| --- | --- | --- |
| Facts found | 36 of 60 | 45 of 60 |
| Right result first | 20 of 60 | 33 of 60 |

The same direction holds in each of the three sets: facts found go from 11 to 12 (development), 12 to 15 (test) and 13 to 18 (chat), and right-result-first goes from 7 to 10, 7 to 12 and 6 to 11. Question by question, the final search found the fact on 10 questions that the old search missed.

### 1.3 Follow-up questions

A follow-up like "and the docker images one?" is hard to search as typed. On the 15 follow-ups in our chat set, searching them as typed found 4 facts with the old search and 8 with the new one. A hand-written standalone version of each follow-up finds 12 of 14, so there is more to gain by rewriting follow-up questions before searching. The live chat already makes a second search in the model's own words for follow-ups.

### 1.4 Dates

On a team member's own chat, the question "what do I need to do for next week?" used to bring back unrelated pages. It now brings back the Docker Compose assignment page and gives the right due date (Wed, Oct 28, 3:00 PM PDT).

## 2. Robustness and reliability testing

### 2.1 Odd inputs, failures and hostile text

`backend/tests/test_robustness.py` has 16 tests, and all pass. The chat gives a normal reply to:

- empty questions and questions with only spaces
- a 20,000-character question
- non-Latin text and control characters
- injection-style text such as SQL and script tags

If the search fails or the model connection drops mid-answer, the server returns one clean error. A round limit stops a model that keeps calling tools. Instructions hidden in course text stay in the search result and never reach the system prompt. If the local re-sorting model fails, the chat falls back to the rank-merged order.

### 2.2 Noisy questions

32 answerable single-turn questions, with a fixed random seed.

| Question variant | Facts found | Right result first |
| --- | --- | --- |
| Clean | 27 | 22 |
| All caps, no punctuation | 28 | 22 |
| Extra spaces and newlines | 27 | 22 |
| Filler words around the question | 27 | 18 |
| Typos (about 1 word in 4) | 23 | 20 |
| Cut off at 60% of the words | 15 | 7 |

The search handles case, punctuation, spacing and filler words with no loss in facts found. Typos cost 4 of 27 facts. Cutting a question short removes information the search never had.

### 2.3 Load

160 searches, 8 at a time: 0 errors, median 3.1 seconds, 95th percentile 4.4 seconds. This is fine for one student on one computer.

### 2.4 Questions the course cannot answer

The chat said it could not find an answer on 6 of 6 questions that the course does not cover (for example the wifi password for a room, or the guest speaker in week 10). It did not make anything up.

## 3. Responsible deployment

### 3.1 What we added

| Risk | Protection |
| --- | --- |
| Wrong answers | The prompt says: use course facts only from search results, copy dates exactly, and say so when nothing is found. Every answer cites numbered sources the student can open. |
| Misuse (graded work) | The prompt says not to solve exams, quizzes, graded assignments or labs, and to explain the idea instead. On 6 misuse prompts the chat said no clearly on 5. It answered all 4 normal study and due-date questions as before. |
| Prompt injection | Course text goes to the model as search results, never as instructions. This is tested. |
| Privacy and deletion | `DELETE /data` removes the whole data folder (index, synced files, conversations, memory, study sets, settings) and the stored credentials. This is tested. Keys are kept in the system Keychain. |
| Failure handling | Search, model and network errors return a clear message, not a crash. |

### 3.2 Remaining limitations

- **Sample sizes are small.** The misuse check used 6 prompts and the unanswerable check used 6 questions. They show the behavior works, not that it always will.
- **Answers can still be wrong.** We found mistakes by reading answers: wrong Sunday dates in a calendar table, a missed instructor name, and a missed required book. We did not measure an answer-quality gain, because our automatic grader was too noisy to trust.
- **Exam text is in the index.** Canvas assignment descriptions are indexed, including a midterm coding question. The chat refuses to solve it but still describes it.
- **Deletion is incomplete.** There is no sign-out or delete button in the app yet, and the app must remove its own Keychain items. Anything already sent to the model provider stays there. Recording consent is not done in this track.
- **Security.** The local server accepts requests from any page on this computer. We believe a web page cannot call `DELETE /data`, but we did not test it.
- **Fairness and accessibility.** We did not evaluate either. Answers are only as good as the posted material, so weak or missing recordings give weaker answers. The chat is English only. We did not check the app with a screen reader or keyboard only.
- **Typos and load.** Typos lose some facts. Concurrent searches wait in line, so this would not scale to many users.

### 3.3 Next steps

1. Keep exam and quiz text out of the index.
2. Add the sign-out and delete-all button to the app.
3. Ask a follow-up question when the request is vague.
4. Handle typos better with a keyword search that tolerates misspellings.
5. Have a person grade a fixed sample of answers.

### 3.4 How to reproduce

`uv run python3 scripts/ask_modes_eval.py --set sprint8-test --retrieval-only --index <frozen index> --out PATH` and `scripts/robustness_eval.py --index <frozen index> --out PATH`.
