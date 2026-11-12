# RAG Gaps from the "Building RAG Agents with LLMs" Course

**Status (2026-11-11):** Task 1 is merged (PR #55). Task 2 is merged (PR #57); see its [implementation and evidence](2026-11-10-answer-feedback.md). Task 5 is built as far as the development sample and merged (PR #56), together with what it led to: two memory fixes, search over past chats, a recall limit of 10 and `gpt-5-mini` as the default model. Task 3 is built on branch `index-filters` (2026-11-11). Tasks 4, 6, 7 and 8 are not started.

**Goal:** Close the eight gaps found by comparing Second Mind with NVIDIA's "Building RAG Agents with LLMs" notebooks (`docs/RAG with LLMs/`, gitignored). Most of what the course teaches is already here and often goes further (hybrid search with rank fusion, a cross-encoder reranker, the memory layer, the ask-modes eval). These eight are what's missing or unfinished.

**Deadlines:** Sprint 9 (beta and independent testing) is due 2026-11-17. The final (technical evidence against baselines) is due 2026-12-01. Tasks 1 to 4 help the beta; tasks 5 to 8 are evidence for the final. Sprint 9's main graded work (an outside tester running the core workflow, deployment steps, user docs) is not in this list.

**Rule for every task:** tests first, then the code. A change to search or chat is measured with `backend/scripts/ask_modes_eval.py` before it's called better. Prompts are tuned on development cases only. The frozen Sprint 8 sets (`sprint8-test`, `sprint8-chat`) are run once, when the design is settled.

## Before the tasks

- **OpenAI key for evals.** The eval reads it from the macOS Keychain, so running it may show a Keychain prompt. Each before/after chat run with the gpt-4o judge costs well under $1.
- **Frozen index for course 55710.** Only courses 55016 and 56350 are indexed on this machine, so 8 of the 13 `sprint8-chat` cases can't run here. A copy of the frozen Sprint 8 index from whoever ran it lets every case run. A fresh Canvas sync would give different numbers.
- **Overlap with the generative UI plan** (`2026-10-28-chat-generative-ui.md`). Its steps change `chat.answer()`, as tasks 1 and 7 do, and `ChatPanel.tsx` / `Answer.tsx`, as task 2 does, so merge one before rebasing the other. Its `show_deadlines` tool covers deadline listings (see task 8).

## Tasks

### 1. Rewrite follow-up questions before the first search (beta) — done, merged in PR #55

- **Why:** a follow-up searched as typed ("and the final?") found its fact on 8 of 15 turns. A hand-written stand-alone version found 12 of 14 (Sprint 8 report §1.3). Live chat graded 7 of 16 follow-up turns bad.
- **Built:** `chat.standalone_query()` makes one JSON call on follow-ups only. The rewritten question is the first search. Any failure falls back to the student's words. 10 new tests; all 554 backend tests pass.
- **First measurement (2026-11-09):**
  - Prompt tuned on `heldout` H9, H10, H18, H19.
  - `sprint8-chat` run on the 5 cases whose courses are indexed here (CH6 to CH10, 6 follow-up turns), without the reranker (its model isn't converted on this machine).
  - The first search found the turn's fact on 3 of 6 turns, up from 2 of 6. Hand-written rewrites also find 3 of 6.
  - Any search in the turn found it on 3 of 6 both before and after: the model's forced own search already caught the turn the rewrite fixed.
  - Median time per follow-up turn went from 2.7 s to 3.2 s.
  - Judge grades didn't move beyond noise (the same untouched first turn graded good, good, then bad across three runs).
- **Rerun with the reranker (2026-11-09, same 5 cases, 6 follow-up turns):**
  - First search found the fact on 2 of 6 before and 2 of 6 after. Any search in the turn: 3 of 6 both ways. Median time per follow-up turn 3.1 s before, 4.0 s after.
  - Turn by turn, the rewrite is already at its ceiling here. CH7.2 and CH8.2 hit either way. CH9.2 is the only wording miss: the model wrote "TA", the hand rewrite "teaching assistant", and the syllabus chunk says the latter. CH6.2 is a labeling miss: search returns the Task 4 objectives page, which answers the question, but the gold fact string is a phrasing from a different page. CH6.3 misses for the hand rewrite too (a 435-character chunk competing with other Task 4 pages). CH10.2's fact isn't in the local index at all, so it can't be scored here.
  - So on this sample the rewrite buys nothing and costs about 0.5 to 0.9 s per follow-up. The Sprint 8 gap (8 of 15 as typed, 12 of 14 rewritten) came mostly from course 55710's cases, which can't run here.
- **Rewrite on, forced own-words search off (2026-11-09, `chat.FOLLOW_UP_MUST_SEARCH = False`, same 6 turns):** first search 2 of 6, any search 2 of 6, median 2.8 s per turn. It saves 0.3 s against main and loses one fact (CH9.2: the model's second search said "Teaching Assistant", which matched; its rewrite said "TA", which didn't). Not worth it on this sample.
- **Sprint 9 chat set (2026-11-10).** Nobody on the team can sync 18-654 any more, so `sprint9-chat` was written for the two courses that are indexed: 14 chats, 26 follow-up turns, every fact checked word for word in the index text before any search ran. Frozen like the Sprint 8 sets. Search only, as typed against hand-written rewrites: 17 of 26 against 24 of 25.

  | 26 follow-up turns | Main | Rewrite | Rewrite, no forced search |
  | --- | --- | --- | --- |
  | First search finds the fact | 17 | 24 | 25 |
  | Any search finds it | 23 | 24 | 25 |
  | Median seconds per turn | 2.9 | 4.0 | 2.8 |
  | Searches per turn | 2 | 2 | 1 |
  | Judge: good / OK / bad | 18 / 5 / 3 | 21 / 3 / 2 | 18 / 3 / 5 |

  The 5 "bad" grades without the forced search were read by hand: 4 answers state the fact correctly (main's near-identical answers were graded OK or bad too), and 1 (N7.2, "interview two practitioners") is missed by every version because no search returns that chunk.
- **Decision:** ship the rewrite with the forced search off. It stays on when the rewrite call fails, and `chat.FOLLOW_UP_MUST_SEARCH = True` brings the old behavior back for comparisons.
- **Left:** nothing. N7.2 goes to task 3 as a search miss.
- **Proof:** the before/after table, and the PR.

### 2. Thumbs up/down on chat answers (beta) — built, verified

- **Why:** the course's release advice is to collect feedback before rollout. The app has no way to flag an answer. Sprint 9's outside tester can flag bad answers during the test, which feeds the independent-test report and task 6.
- **Build:** up and down buttons under each finished answer, with an optional short note. Stored on the saved turn in the local conversation file, so nothing leaves the computer. Add a route to list flagged turns for a course.
- **Proof:** tests for saving and listing; screenshots of an answer with each state.
- **Built (2026-11-10):** Helpful / Not helpful buttons, removable ratings, and optional notes up to 500 characters. Feedback stays on the saved turn locally and is restored when reopening the chat. `GET /courses/{course_id}/feedback` lists thumbs-down turns for review. The final stream event identifies the saved turn, so failed answers cannot shift feedback onto another answer.
- **Verified:** 593 backend tests passed (9 skipped), 5 frontend interaction tests passed, production build passed. [Screenshots and verification scope](../evaluations/answer-feedback/README.md).

### 3. Keep graded exam and quiz text out of the index, and drop junk chunks (beta) — built on branch `index-filters`

- **Why:** Sprint 8 found a midterm coding question in the index, and an interviewee raised graded-quiz exposure (Sprint 8 next step 1). The course also drops near-empty and mostly-numeric chunks, and `indexing.py` had no such filter.
- **What leaked:** two assignments in course 55710, "Midterm Coding Question (access only through Midterm Exam)" and "Midterm Exam- Requires Respondus LockDown Browser". Search returned both for "When is the midterm exam?" and "How much is the final exam worth?". Files and pages weren't the problem: "13 - MidtermReview.pdf" is review material and stays.
- **Built (2026-11-11):**
  - `course_sync.is_exam_or_quiz()`. Canvas's own fields come first: `is_quiz_assignment`, `"online_quiz"` in `submission_types`, `is_quiz_lti_assignment` (New Quizzes) and `require_lockdown_browser`. The name is the fallback (exam, midterm, quiz, Respondus, LockDown Browser) for exam parts posted as ordinary assignments.
  - An exam keeps its name, due date and points, so "when is the midterm?" still works; its description is never indexed. An exam with neither is left out.
  - Its manifest version gets an `|exam` suffix, so an exam that an older version of the app indexed in full reads as changed, and its text is deleted on the next sync.
  - `indexing.is_junk()`: under 8 characters, or under 25% letters. It's applied to PDF pages, slides and Canvas sections, and not to transcripts or the student's own notes. A section is judged together with its own heading.
  - 24 new tests. All 662 backend tests pass (9 skipped).
- **A miss caught by the eval:** the first version judged a section without its heading and dropped "Syllabus › Units\n- 12", the answer to `sprint9-chat` N5.3 ("how many units is this course?"). With the heading counted, the fact is back.
- **Measured on the two local courses** (a copy of the index with the dropped chunks removed and its full-text index rebuilt):
  - Chunks: 55016 185 → 185, 56350 202 → 200 (two Zotero PDF pages, "Enjoy!" and "Zotero").
  - None of the 34 assignments in either course is an exam or quiz by the rule, so nothing changes there. The exam rule is covered by tests only; course 55710 isn't available.
  - `--retrieval-only`, local cases only: `sprint8` (P10–P15) facts found 4 of 4 before and after; `heldout` recall@5 0.91 both; `sprint9-chat` facts found 30 of 40 both. One result list changed (N9.2's fifth result).
- **Left:** an exam already indexed on someone's machine loses its text on their next sync. Junk chunks already indexed stay until their item changes on Canvas.

### 4. One retry when a model reply isn't valid JSON (beta)

- **Why:** `llm.complete_json` returns `None` on bad JSON. Memory extraction then saves nothing for that turn. Consolidation falls back to adding a memory, which can create duplicates. Copilot has no JSON mode, so it's more exposed.
- **Build:** on a parse failure or a reply of the wrong shape, one retry that adds "Return exactly one valid JSON object." Count retries in the log.
- **Proof:** tests for retry-then-success and retry-then-give-up.

### 5. Build the memory evaluation (final) — development sample done, in PR #56

- **Why:** the LongMemEval harness in `docs/specs/2026-09-25-agent-memory-evaluation-design.md` was never built, so the memory layer has no measured numbers.
- **Build:**
  - The harness from that spec, on the LongMemEval subset, with the shipped chat without memory as the baseline.
  - Tool-sequence checks on a small student set:
    - `recall_memory` called when the answer needs it
    - "forget that" deleting the right memory
    - "what was it before?" using `include_history`
- **Built (2026-11-10):** `backend/scripts/memory_eval.py`, on LongMemEval's oracle split, graded by `gpt-4o` with the benchmark's own prompts.
  - It compares the shipped chat's window (S0), the whole history (S1), search over raw turns (S2), the memory layer (S3) and the memory layer with past-chat search (S4).
  - It writes each question's memories once and runs 8 questions at a time: 60 questions in about 50 seconds for $0.04 after the first run.
- **First result:** on 30 questions the memory layer scored lowest (14 of 27, against 23 for raw-turn search), at about a sixth of the prompt tokens.
- **What the misses led to,** all in PR #56:
  - The no-grades filter was dropping "lost 10 pounds". Fixed.
  - The extraction prompt now asks for dated events and the student's specifics.
  - **Search over past chats** (`search_past_chats`, design in `docs/specs/2026-11-10-past-chat-search-design.md`). Memory never stores what the assistant said, so "which video did you recommend?" scored 0 to 2 of 10; with the search it scores about 6.
  - **Recall returns 10 memories, not 5.** Counting questions need every matching memory: 35.2 against 32.5 of 54 on multi-chat questions, four runs each.
  - **`gpt-5-mini` is the default OpenAI model.** It scored 49.5 to 51.5 of 58 against 42 to 43 for `gpt-4o-mini`. In course chat it is about four times slower (11.7 s a turn against 2.6 s), and a gain there is not established.
- **Tried and dropped:** writing memories with a stronger model (no difference), and an automatic past-chat search (one more question right for twice the tokens).
- **What the numbers are worth:** a single run on 60 questions varies by up to four questions. The recall-limit and model results use four runs each; the earlier steps are single runs and show direction only.
- **Left:**
  1. The full benchmark, where each history has about 50 sessions. The oracle split used so far holds only the sessions with the answer.
  2. The student-memory set and the tool-sequence checks above. Nothing coursework-specific is measured yet.
  3. Whether the chat follows the "check a past answer's course fact with course search" rule.
  4. The report in `docs/evaluations/`. The results so far are in PR #56's description and commit messages.
- **Proof so far:** PR #56.

### 6. A grader you can trust (final)

- **Why:** Sprint 8 called the automatic grader "too noisy to trust", and "have a person grade a fixed sample" is still open. The final needs believable answer-quality numbers.
- **Build:**
  1. Hand-grade a fixed sample of about 30 answers, including any flagged in task 2.
  2. Measure how often the gpt-4o judge agrees.
  3. Try the course's pairwise format (old answer vs new answer, verdict first) and keep whichever agrees with people more.
  4. Add generated questions that need two documents, to grow the 60-question set.
- **Proof:** the agreement numbers and the chosen grading method, written up in `docs/evaluations/`.

### 7. A classifier guard for graded-work requests (final)

- **Why:** the "don't do graded work" rule is prompt-only, and it held on 5 of 6 misuse prompts in Sprint 8. The course's method is a logistic regression on question embeddings that switches to a stricter prompt instead of refusing outright. It costs one local embedding, which the bge model already loaded can do.
- **Build:**
  - A labeled set of misuse and normal questions (real ones plus generated ones), split into train and held-out.
  - The classifier, loaded at startup.
  - A high score adds a stricter instruction to that turn's system prompt.
- **Proof:** held-out accuracy and false-alarm rate. Misuse prompts refused before and after. Normal study questions still answered.

### 8. Listing questions (final, if time)

- **Why:** "What are all the readings for week 3?" can't be answered from five search results. The course adds an "available documents" overview for this.
- **Build:** decide with the generative UI plan first. Its `show_deadlines` covers assignments and due dates. What's left is files, pages and lectures. A `list_course_items` tool built from the synced Canvas data would cover them.
- **Proof:** a few listing questions added to the eval, answered before and after.
