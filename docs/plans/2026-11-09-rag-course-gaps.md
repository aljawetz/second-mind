# RAG Gaps from the "Building RAG Agents with LLMs" Course

**Status:** Task 1 merged in PR #55. Task 2 built and verified on branch `chat-answer-feedback`; see its [implementation and evidence](2026-11-10-answer-feedback.md). Tasks 3 to 8 not started.

**Goal:** Close the eight gaps found by comparing Second Mind with NVIDIA's "Building RAG Agents with LLMs" notebooks (`docs/RAG with LLMs/`, gitignored). Most of what the course teaches is already here and often goes further (hybrid search with rank fusion, a cross-encoder reranker, the memory layer, the ask-modes eval). These eight are what's missing or unfinished.

**Deadlines:** Sprint 9 (beta and independent testing) is due 2026-11-17. The final (technical evidence against baselines) is due 2026-12-01. Tasks 1 to 4 help the beta; tasks 5 to 8 are evidence for the final. Sprint 9's main graded work (an outside tester running the core workflow, deployment steps, user docs) is not in this list.

**Rule for every task:** tests first, then the code. A change to search or chat is measured with `backend/scripts/ask_modes_eval.py` before it's called better. Prompts are tuned on development cases only. The frozen Sprint 8 sets (`sprint8-test`, `sprint8-chat`) are run once, when the design is settled.

## Before the tasks

- **OpenAI key for evals.** The eval reads it from the macOS Keychain, so running it may show a Keychain prompt. Each before/after chat run with the gpt-4o judge costs well under $1.
- **Frozen index for course 55710.** Only courses 55016 and 56350 are indexed on this machine, so 8 of the 13 `sprint8-chat` cases can't run here. A copy of the frozen Sprint 8 index from whoever ran it lets every case run. A fresh Canvas sync would give different numbers.
- **Overlap with the generative UI plan** (`2026-10-28-chat-generative-ui.md`). Its steps change `chat.answer()`, as tasks 1 and 7 do, and `ChatPanel.tsx` / `Answer.tsx`, as task 2 does, so merge one before rebasing the other. Its `show_deadlines` tool covers deadline listings (see task 8).

## Tasks

### 1. Rewrite follow-up questions before the first search (beta) — built, measured

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
- **Left:** open the PR. N7.2 goes to task 3 as a search miss.
- **Proof:** the before/after table, and the PR.

### 2. Thumbs up/down on chat answers (beta) — built, verified

- **Why:** the course's release advice is to collect feedback before rollout. The app has no way to flag an answer. Sprint 9's outside tester can flag bad answers during the test, which feeds the independent-test report and task 6.
- **Build:** up and down buttons under each finished answer, with an optional short note. Stored on the saved turn in the local conversation file, so nothing leaves the computer. Add a route to list flagged turns for a course.
- **Proof:** tests for saving and listing; screenshots of an answer with each state.
- **Built (2026-11-10):** Helpful / Not helpful buttons, removable ratings, and optional notes up to 500 characters. Feedback stays on the saved turn locally and is restored when reopening the chat. `GET /courses/{course_id}/feedback` lists thumbs-down turns for review. The final stream event identifies the saved turn, so failed answers cannot shift feedback onto another answer.
- **Verified:** 593 backend tests passed (9 skipped), 5 frontend interaction tests passed, production build passed. [Screenshots and verification scope](../evaluations/answer-feedback/README.md).

### 3. Keep graded exam and quiz text out of the index, and drop junk chunks (beta)

- **Why:** Sprint 8 found a midterm coding question in the index, and an interviewee raised graded-quiz exposure (Sprint 8 next step 1). The course also drops near-empty and mostly-numeric chunks, and `indexing.py` has no such filter.
- **Build:**
  - In `course_sync.sync_course` / `canvas.list_assignments`, skip graded quizzes and exams. Decide the rule from Canvas's own fields (quiz assignments, submission types) before falling back to names.
  - In `indexing.py`, drop chunks under a minimum length or mostly non-letters.
- **Proof:**
  - Tests for both rules.
  - Chunk counts before and after on the two local courses.
  - `--retrieval-only` on `sprint8` showing facts found didn't drop.

### 4. One retry when a model reply isn't valid JSON (beta)

- **Why:** `llm.complete_json` returns `None` on bad JSON. Memory extraction then saves nothing for that turn. Consolidation falls back to adding a memory, which can create duplicates. Copilot has no JSON mode, so it's more exposed.
- **Build:** on a parse failure or a reply of the wrong shape, one retry that adds "Return exactly one valid JSON object." Count retries in the log.
- **Proof:** tests for retry-then-success and retry-then-give-up.

### 5. Build the memory evaluation (final)

- **Why:** the LongMemEval harness in `docs/specs/2026-09-25-agent-memory-evaluation-design.md` was never built, so the memory layer has no measured numbers.
- **Build:**
  - The harness from that spec, on the LongMemEval subset, with the shipped chat without memory as the baseline.
  - Tool-sequence checks on a small student set:
    - `recall_memory` called when the answer needs it
    - "forget that" deleting the right memory
    - "what was it before?" using `include_history`
- **Proof:** a report in `docs/evaluations/` with accuracy per question type and cost per turn.

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
