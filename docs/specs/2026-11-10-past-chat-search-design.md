# Search over past chats — design

**Status:** approved by Yongjie on 2026-11-10 with the three recommendations in §7. Step 1 in progress.
**Owner:** Yongjie
**Builds on:** [agent memory design](2026-09-25-agent-memory-design.md), [memory evaluation](2026-09-25-agent-memory-evaluation-design.md)

## 1. The gap

The memory layer keeps what the student said about themselves: their team, preferences, progress. It deliberately doesn't keep what the assistant said, so a wrong or made-up answer can never turn into a remembered fact.

The memory evaluation (`backend/scripts/memory_eval.py`, LongMemEval oracle split, 60 development questions) shows what that costs:

| Question type | Memory layer (S3) | Search over raw turns (S2, on the first 30) |
| --- | --- | --- |
| What the assistant said ("remind me which video you recommended") | 0 to 2 of 10 | 5 of 5 |
| Combining facts from several chats ("how many model kits have I bought?") | 3 to 5 of 9 | 2 of 3 |

Four models and two prompts for writing memories all landed between 32 and 37 of 58. Neither a better prompt nor a stronger model closes these two gaps. They are structural: the details were never stored.

Plain search over raw turns was the best of the four systems tested (23 of 27 on the first sample). The turns it searches are already on the student's disk, in their saved chats. A new chat just can't reach them.

## 2. What this adds

A third lookup beside course search and memory: **search the student's own past chats in this course**.

- Memory stays as it is: a short, clean profile of what the student told the assistant.
- Past-chat search answers "what did we talk about?" and "what did you tell me?" from the saved turns themselves.
- Nothing the assistant said becomes a memory.

## 3. What is searched

- **Unit:** one turn of a saved chat: the student's question and the assistant's answer together, with the chat's title and the turn's date.
- **Scope:** every saved chat in the same course, except the one being answered (its history is already in view).
- **Where the index lives:** a new `turns` table in the course's existing `memory.db`, with the text, an embedding from the app's local BGE model, and an FTS5 row. Same file, so deleting a course or wiping data takes it along.
- **Who writes it:** the memory worker. It already reads every new turn in the background, so it indexes the turn in the same pass. No model call: embedding is local.
- **Old chats:** each chat file gets a `turns_indexed_upto` counter, like `memory_processed_upto`, so chats saved before this feature are indexed on the worker's next pass.

## 4. How it is searched

The same recipe as memory recall and course search, so there is one way of ranking to reason about:

- vector search (cosine, with a cutoff) plus keyword search (BM25), merged by rank
- top 5 turns, each answer cut to a fixed length (starting value 600 characters, tuned on the development sample)
- a mild recency weight, as in memory recall

## 5. How the chat uses it

- **A tool, `search_past_chats(query)`**, offered only when memory is on. Its description: what the student and the assistant said in earlier chats in this course; not course material.
- **Results are labeled `[P1]`, `[P2]`**, with the chat title and date, and say who said what:

  ```
  [P1] "Posture videos", 2026-05-22
  Student: Can you recommend YouTube videos on workplace posture?
  Assistant: 1. "How to Sit Properly at a Desk to Avoid Back Pain" ...
  ```
- **Rules, enforced in code where possible, as with memory:**
  - `[P…]` labels are stripped from the answer. A past chat is never a citation.
  - A course fact found only in a past answer (a date, a weight, a policy) must be checked with `search_course` before it is repeated. The past answer may have been wrong, or the course may have changed. The prompt states this; the eval checks it.
  - The answer says where it came from in plain words ("In our chat on May 22 I suggested…").

## 6. Privacy and deletion

- **Deleting a chat** removes its turns from the index. The hook exists already (`forget_conversation`).
- **Delete all data** removes `memory.db`, so the index goes with it.
- **"Forget that"** still only removes memories. The reply already says the words remain in the saved chat; they will also remain searchable until that chat is deleted. The reply will say so.
- **Grades and deadlines.** Memory never stores them (design spec §5.2). Raw turns can contain them. See decision 1.
- **Other courses** are never searched: the index is per course, like memory.

## 7. Decisions (made 2026-11-10: all three as recommended)

1. **Turns that mention grades or deadlines.** Recommended: don't index them, using the same filter memory uses. It keeps one rule for the whole memory database. The cost is that some harmless turns go unsearchable when the filter is over-cautious (it has been tightened once already).
2. **Tool only, or automatic too.** Recommended: tool only at first. The chat already runs course search and memory recall up front on every question; a third automatic search adds tokens to every turn for a need that is occasional. If the eval shows the model fails to call the tool when it should, add an automatic search for questions that refer to an earlier chat.
3. **How much of each past answer to show.** Recommended: start at 600 characters and tune on the development sample. Long answers are where "the 27th item on that list" lives, so this number trades tokens against exactly the questions this feature is for.

## 8. How it will be measured

- **New system S4 in `memory_eval.py`:** S3 plus past-chat search. Same 60 development questions, same judge.
  - Target: the two weak types in §1, without losing ground on the others.
  - Reported with it: prompt tokens per answer (S3 uses about 800; S2 about 4,000) and how often the tool is called.
- **Tool use:** on questions that need a past chat, was `search_past_chats` called? On questions that don't, was it left alone?
- **The stale-fact rule:** a few scripted chats where a past answer holds a course fact that is wrong. The new answer must search the course and not repeat it.
- **No regression in course chat:** `ask_modes_eval.py --set sprint9-chat` with memory on, before and after.
- The S-split test (each history about 50 sessions) stays the final check, once the design is settled.

## 9. Steps

Each is test-first, and committed on its own.

1. `turns` table, indexing function, and the grades filter on turns (decision 1).
2. Search function: vector plus keyword, rank fusion, top 5.
3. Worker indexes new turns and backfills old chats.
4. `search_past_chats` tool in `chat.answer`, label stripping, prompt rules.
5. Deleting a chat removes its turns; tests for every path in §6.
6. S4 in `memory_eval.py`, run on the development sample, report.

## 10. Risks

- **Stale or wrong past answers repeated as fact.** The check-with-course-search rule and its eval are there for this. It is the main risk.
- **More tokens per answer.** Bounded by top 5 and the per-turn cut; measured in step 6.
- **A third tool confuses a small model.** `gpt-4o-mini` already chooses between two tools. The tool-use numbers in §8 will show whether three is too many.
- **Index size.** One embedding per turn. A heavy semester is a few thousand turns, which a brute-force scan handles in milliseconds, as memory's does.
