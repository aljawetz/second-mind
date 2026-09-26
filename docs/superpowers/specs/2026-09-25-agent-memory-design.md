# Agent memory for Second Mind — design

**Status:** draft for team review
**Owner:** Yongjie
**Sprint:** 5 (core prototype, due 2026-09-29)
**Depends on:** [conversation history plan](../plans/2026-09-23-conversation-history.md), Tasks 1–2 (turns
saved on disk). If those aren't built when this work starts, they become its first step.
**Companion:** [evaluation design](2026-09-25-agent-memory-evaluation-design.md)
**Blocks:** a "What Second Mind remembers" screen (Sprint 6); memory in the assignment explainer and
study artifacts.

## 1. Problem

Second Mind remembers the course, but not the student.

- `/ask` saves nothing. Chat turns live in `HomeView.tsx` state and are lost when the student
  navigates away or restarts the app.
- Inside one chat, the model sees only the last 6 turns, with answers cut to 1,500 characters
  (`chat.HISTORY_TURNS`, `chat.HISTORY_ANSWER_CHARS`). Older turns are dropped, not summarized.
- Nothing carries over from one chat to the next. Say a student writes on Monday "I'm on team 4,
  we picked the recommender project", then asks on Wednesday "what does our next milestone
  need?" The Wednesday answer doesn't know which project they mean.
- The only way anything is forgotten is a hard delete: removing a course, deleting a session, or
  a re-synced file replacing its old chunks. There's no way to mark a fact as replaced by a
  newer one.

## 2. Goals and non-goals

**Goals**

1. One memory module that every Second Mind agent reads and writes through. Chat uses it first;
   the assignment explainer and study artifacts come next.
2. Memory with a full lifecycle: capture, extract, consolidate, index, recall, compress, forget.
3. Stays local and per course, with no new sidecar dependencies.
4. Runs without Canvas or the app, so it can be tested on public data (companion spec).

**Non-goals (this spec)**

- A hosted or multi-student memory service.
- The memory screen in the app (Sprint 6). This spec only adds list and delete endpoints.
- Embedding images. BGE is text-only, and an image encoder would bring back torch, which
  [rag-pipeline.md](../../architecture/rag-pipeline.md) §3 worked hard to keep out of the bundle.
- Any change to course indexing or course search.
- LLM providers other than OpenAI.

## 3. What gets remembered

| Memory type | `kind` in code | What it holds | Example | Written by | Leaves recall when |
|---|---|---|---|---|---|
| Long-term: course knowledge | (course index) | Course material | Syllabus grading table | Canvas sync, session capture (unchanged) | The Canvas item changes or is removed (unchanged) |
| Long-term: about the student | `fact` | Stable facts and preferences the student stated | "The student is on team 4 with Priya and Ken." / "The student wants code examples in Java." | Extraction (§5.2) | Superseded or forgotten. Never because of age |
| Conversational | `event` | Something that happened at a particular time | "On 2026-09-22 the student said they missed Class #5." | Extraction | Archived by decay (§5.7) |
| Conversational | `summary` | One summary per conversation | "Asked about stubs vs mocks; unsure when to verify calls." | Compression (§5.6) | Archived by decay |
| Task | `task` | The student's own goal or progress on course work | "The student finished part 1 of Assignment 3 and is stuck mocking the email service." | Extraction | Replaced by a newer task memory; archived 30 days later |

The course index is not copied into memory. Memory sits beside it, and chat searches both.

**Memory is stored per course**, in `~/.secondmind/courses/<id>/memory.db`. This follows the same
isolation rule as everything else (design spec §5.1):

- A fact from one course can't show up in another.
- "Assignment 3" in two different courses can never be merged into one memory.
- Removing a course already deletes its directory, so its memories go with it at no extra cost.

Facts that apply to every course (the student's name, preferred language) are also stored per
course for now. A student-level store is future work.

## 4. Storage

Memory lives in SQLite, one file per course. Embeddings are stored as float32 blobs and searched
by brute-force cosine similarity in numpy. Keyword search uses SQLite's built-in FTS5, which the
local Python's SQLite (3.53) has; this still needs checking in the frozen build.

**Why not LanceDB, which course search already uses:**

- Memory rows change constantly: they get superseded, archived, and their access counts go up.
  SQLite handles row updates inside transactions; LanceDB is built for appending.
- The team has already hit LanceDB schema-inference bugs twice (rag-pipeline.md §6).
- One course's memory will be a few thousand rows at most. 5,000 × 384 floats is 7.7 MB, and a
  full cosine scan over that takes milliseconds.
- No new dependency. numpy already comes in through onnxruntime and pandas.

```sql
CREATE TABLE memory (
  id            TEXT PRIMARY KEY,               -- "m-" + 12 hex chars
  kind          TEXT NOT NULL,                  -- fact | event | task | summary
  text          TEXT NOT NULL,                  -- one self-contained statement, <= 300 chars
  importance    INTEGER NOT NULL,               -- 1..5, from extraction
  event_time    TEXT,                           -- when it happened or became true (ISO 8601)
  created_at    TEXT NOT NULL,
  valid_to      TEXT,                           -- NULL = current; set when superseded or closed
  superseded_by TEXT REFERENCES memory(id) ON DELETE SET NULL,
  status        TEXT NOT NULL DEFAULT 'active', -- active | archived
  task_ref      TEXT,                           -- e.g. "assignment:4412" when resolvable (P1)
  conversation_id TEXT,                         -- summary memories only: one per conversation
  access_count  INTEGER NOT NULL DEFAULT 0,
  last_accessed TEXT,
  embedding     BLOB NOT NULL                   -- 384 float32, L2-normalized (OnnxBgeEmbedding)
);
CREATE TABLE provenance (                       -- which saved turns a memory came from
  memory_id       TEXT NOT NULL REFERENCES memory(id) ON DELETE CASCADE,
  conversation_id TEXT NOT NULL,
  turn_index      INTEGER NOT NULL
);
CREATE TABLE entity (id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL);   -- lowercased
CREATE TABLE memory_entity (
  memory_id TEXT NOT NULL REFERENCES memory(id) ON DELETE CASCADE,
  entity_id INTEGER NOT NULL REFERENCES entity(id),
  PRIMARY KEY (memory_id, entity_id)
);
CREATE VIRTUAL TABLE memory_fts USING fts5(memory_id UNINDEXED, text);
CREATE TABLE ops_log (                          -- every lifecycle decision, for debugging and eval
  at TEXT NOT NULL, op TEXT NOT NULL, memory_id TEXT, reason TEXT NOT NULL
);
```

- `ops_log.reason` holds the decision label (for example `"UPDATE of m-1a2b… by extraction"`),
  never memory text. A hard delete (§5.7) also removes the memory's `ops_log` rows.
- FTS5 is a standalone table written in the same transaction as `memory`, not an
  external-content table with triggers. It's simpler, and there's nothing to drift out of sync.
- Each `MemoryStore` has one connection, guarded by its own lock, so one store can be shared
  between threads. Different stores on the same file (the worker's, a request thread's) rely on
  WAL mode and a 10-second busy timeout. Consolidation's read-then-write is safe without a
  per-course lock, because only the single background worker consolidates (§5.1).
- A store is used as `with MemoryStore(path) as store:`. Python 3.13+ warns about SQLite
  connections that are garbage-collected without being closed; the strict test run found this.

## 5. Lifecycle

```
/ask finishes streaming ─► 1 Capture   save the turn; queue it for the memory worker
                           (background, never delays the answer)
                           2 Extract   one LLM call → candidate memories + updated conversation summary
                           3 Consolidate  each candidate vs similar memories → ADD | UPDATE | INVALIDATE | NOOP
                           4 Index     embedding, FTS row, entity links
next question ──────────►  5 Recall    profile block in the system prompt + automatic recall
                                       + recall_memory tool
                           6 Compress  rolling summary replaces the 6-turn window; summary memory per chat
periodically ───────────►  7 Forget    decay → archive; "forget that" → hard delete; cascades
```

### 5.1 Capture

When `/ask` finishes streaming, `main.py` saves the turn (conversation history plan, Task 2) and
calls `memory.observe_turn(conversation_id, turn_index)`. That puts a job on a queue served by one
background thread. The answer is never delayed, and if the job fails, the turn stays saved and
the error is logged.

- **One worker thread:** memory writes happen one at a time (no racing consolidations), and LLM
  spend stays bounded.
- **Surviving restarts:** each conversation file gains a `memory_processed_upto` turn index. On
  startup, the worker queues any saved turns past that index, so jobs lost to a quit are picked
  up again.

### 5.2 Extract

One gpt-4o-mini call per job, with JSON output and temperature 0.

**Input:**
- The new turn(s): question, plus the answer with its citation markers removed.
- The conversation's current summary, so the model can resolve "it" and "that one".
- The turn's `asked_at` time, so relative dates ("last Tuesday") can be turned into real ones.

The same function accepts a list of turns. The product sends one turn; the benchmark sends a
whole session at a time (evaluation spec §4).

**Output:**

```json
{
  "memories": [
    {"kind": "fact", "text": "The student is on team 4 with Priya and Ken.", "importance": 4,
     "event_time": "2026-09-21", "entities": ["team 4", "priya", "ken"], "task_ref_hint": null}
  ],
  "summary": "Updated summary of the whole conversation, at most 150 words."
}
```

**Prompt rules:**
- Only record what the student said or clearly confirmed. Never record the assistant's own
  suggestions as facts about the student.
- Write each memory as one self-contained, third-person statement.
- Skip course facts (those belong to the course index), small talk, and anything already covered
  by the summary.

**Rules enforced in code** (§6):
- At most 5 memories per turn.
- `kind` must be one of `fact`, `event`, or `task`.
- `importance` is clamped to 1–5 and `text` is cut at 300 characters.
- The grades-and-deadlines filter.

Extraction and summarizing share one call on purpose, so the background cost is one call per turn
plus the occasional consolidation call.

### 5.3 Consolidate

For each candidate:

1. Find active memories of the same kind with cosine similarity ≥ `CONSOLIDATE_SIMILARITY`
   (starting value 0.70, calibrated in the evaluation), up to 5.
2. If there are none, **ADD** the candidate directly, with no LLM call.
3. Otherwise, make one LLM call that sees the candidate and the numbered existing memories, and
   returns one decision:
   - **ADD**: the candidate is new information. Insert it.
   - **UPDATE n**: the candidate replaces memory *n* ("we switched to the fraud project"; "stuck
     on A3" becomes "finished A3"). Set the old memory's `valid_to` to the candidate's
     `event_time` (or now) and its `superseded_by` to the new memory's id, then insert the new
     one.
   - **INVALIDATE n**: the student took something back with no replacement ("I'm not on a team
     anymore"). Set `valid_to` and insert nothing.
   - **NOOP**: already known. No new memory is written. The matched memory's `importance` goes
     up by 1 (capped at 5), and this turn is added to its provenance. Without that, deleting the
     first chat would remove a fact the student also said in another one.
   - **Unusable reply** (unknown decision, or a target number that wasn't shown): ADD. A
     duplicate can be cleaned up later; a lost fact can't be recovered. Logged as
     `consolidation: fallback`, so the evaluation can count how often it happens.

**Superseded memories are kept, not deleted.** That lets the agent answer "which project did we
have before?", and gives an audit trail of why the memory changed. A superseded memory is left out
of normal recall because its `valid_to` is set. Only an explicit request to forget deletes
anything (§5.7).

Every decision is written to `ops_log`.

### 5.4 Index

On insert:
- Compute the embedding with the existing `OnnxBgeEmbedding`. Memories are short, so the
  512-token window is never an issue.
- Write the FTS row.
- Link entities: lowercase, trimmed names, upserted into `entity`.

In P0 the entities are stored but not used; graph expansion is P1 (§5.5).

### 5.5 Recall

Chat gets memory three ways:

1. **Profile block, on every question.** Up to 10 active `fact` memories (by importance, then
   most recent) and up to 5 open `task` memories, about 800 characters in total. They go into
   the system prompt under a fixed heading, fenced as data. This is how preferences like "Java
   examples" apply without any search.
2. **Automatic recall, on every question.** The student's words are run through `recall()`
   before the model starts. If anything passes the relevance cut, the results arrive as a tool
   result (`recall-0`), the same way `chat.answer` already makes the first course search itself.
   The reason is the same too: the ask-modes evaluation found the model doesn't use its tools
   enough unless the first call is made for it. This recall is local and costs milliseconds.
3. **`recall_memory` tool**, next to `search_course`:
   `{"query": str, "include_history": bool}`. Setting `include_history=true` also returns
   superseded memories, each marked with the dates it was true, for questions like "before",
   "used to", or "changed".

**Scoring** (every constant is a starting value, calibrated in the evaluation):

```
candidates   = top 20 active memories by cosine, keeping those with cosine >= MEMORY_SIMILARITY_CUTOFF (0.5)
             ∪ top 5 by FTS5 bm25()
relevance(m) = Σ 1 / (60 + rank of m)        over the lists m appears in (reciprocal rank fusion)
recency(m)   = 1                                            for fact
             = 0.5 + 0.5 · exp(−days_since_last_use / 30)   for event, task, summary
               (last_use = last_accessed, else event_time, else created_at)
weight(m)    = 0.6 + 0.08 · importance                      (1 → 0.68, 5 → 1.0)
score(m)     = relevance · recency · weight                 → top 5
```

- **Why rank fusion and not a score threshold on the combined list:** cosine and BM25 scores
  can't be compared with each other. The team found that out the hard way with LanceDB's hybrid
  mode (the `generation.HybridRetriever` docstring). Only cosine gets a threshold; BM25
  contributes by rank.
- **Why facts don't fade with age:** being on team 4 is just as true in November. Recency only
  matters for things that happened.
- **Reinforcement:** returned memories get `access_count += 1` and `last_accessed = now`. Memories
  that keep being used fade more slowly (§5.7).

**Memory results are shown to the model as `[M1] (fact, since 2026-09-21) The student is on
team 4…`** They are never citable course sources. The prompt says to mention them naturally
("You said earlier that…"). As well, `[M\d+]` markers are stripped from the streamed answer in
code, so a memory can never pass as a course citation.

**Graph expansion (P1).** For the top 3 results, also consider active memories that share an
entity with them, at half the fused score. This connects "stuck mocking the email service"
(entity: *email service*) to a later "which lecture covers that?". The course-index side of the
graph is also P1: entities whose name matches a sync-manifest `display_name` get linked to that
Canvas item, and resolved `task_ref`s come from there.

### 5.6 Compress

Three levels:

1. **Within a conversation.** The fixed 6-turn window is replaced by the conversation summary
   (≤ 150 words, from §5.2) plus the last 4 turns verbatim. Citations are stripped and answers
   capped at 1,500 characters, as today. The summary is stored in the conversation file
   (`summary`, `summary_upto`). If the worker hasn't caught up yet, chat falls back to today's
   window.
2. **Conversation → one `summary` memory.** The same summary is upserted as that conversation's
   `summary` memory, keyed by `conversation_id`, so recall can answer "what did we go over about
   mocks last week?".
3. **Turns → short facts.** Recall never returns raw turns, only extracted memories and
   summaries. The evaluation measures the size ratio of memory to raw conversation.

When a `conversation_id` is sent, `/ask` builds history from disk and ignores the `history` the
client sends. The client's copy can be stale. Requests without an id keep today's behavior, so
`scripts/ask_modes_eval.py` and the existing tests still work.

### 5.7 Forget

1. **Superseding and invalidating** (§5.3): a soft forget. The memory is out of normal recall but
   kept for history questions.
2. **Decay → archive:** a sweep at backend start and after every 20 worker jobs.

   | Kind | Archived when |
   |---|---|
   | `event`, `summary`, importance ≤ 3 | Not recalled for 60 days |
   | `event`, `summary`, importance ≥ 4 | Not recalled for 180 days |
   | `task` | 30 days after `valid_to` is set |
   | `fact` | Never by age; only superseded, invalidated, or forgotten |

   Archived memories are left out of recall and the profile block, including
   `include_history=true` recalls. They still appear in the list endpoint, where the student can
   delete them. Every recall counts as use, so memories that keep being used stay active; the
   idea follows MemoryBank's forgetting curve.
3. **Explicit forget:** a hard delete.
   - **In chat:** the model gets a `forget_memory` tool that takes `M` labels shown to it in this
     turn. Labels are checked against this turn's recall results in code. "Forget that I'm
     auditing" normally surfaces the right memory through automatic recall, and the model then
     deletes it.
   - **Through the API:** `DELETE /courses/{id}/memories/{mid}`.
   - **What gets deleted:** the memory row, its FTS row, its entity links, its provenance, and its
     `ops_log` rows. So do the `summary` memories of the conversations it came from, since they
     may repeat the fact; they're rebuilt on the conversation's next turn.
   - **What it doesn't touch:** the saved chat itself. The tool result tells the model to say so:
     "It's still in your chat from Sep 21; delete that chat to remove it completely."
   - **Gone from the files, not just from queries.** Found while building `store.py`: a plain
     SQL `DELETE` left the text readable in the database files, where a backup tool or disk image
     would still pick it up. Removing each fix in turn showed there are three places, and each
     needs its own measure:
     - SQLite's freed pages keep the old bytes → `PRAGMA secure_delete=ON`.
     - FTS5 records a delete as a marker and keeps the old index segment with the words → an FTS
       `optimize` merge after each delete.
     - The write-ahead log keeps the page as it was before the delete → a `TRUNCATE` checkpoint.
       If another connection is mid-read, the checkpoint can't finish until the next delete.

     `test_memory_store.py` reads the raw files after a delete to check the text is gone.
4. **Cascades:**
   - Deleting a conversation deletes every memory whose provenance points only to that
     conversation.
   - Removing a course deletes `memory.db` along with the course directory, which already happens.
   - Deleting a session has no effect in P0, because sessions don't create memories yet.

All sweep and scoring functions take `now` as a parameter, so the evaluation can replay a dated
semester (or LongMemEval's dated sessions) and get real decay and real "last Tuesday" handling.

## 6. Rules enforced in code, not the prompt

`chat.py` already learned this: rules the prompt alone didn't hold went into code.

| Rule | Where | Why |
|---|---|---|
| No grades, scores, or deadlines in memory | `extract.py`: drop any memory whose text matches grade/score/points/GPA near a number or letter grade, or contains "due"/"deadline". Logged as `filtered` | Design spec §5.2: personal Canvas data is never indexed. Deliberately cautious; the evaluation counts wrongly dropped memories |
| At most 5 memories per turn, 300 chars each, valid kind and importance | `extract.py` | Stops one chatty turn from flooding the store |
| Memory is never cited as course material | `chat.py` strips `[M\d+]` from the stream | Citations must stay course-only |
| Course facts come only from course search | Prompt, plus extraction skips course facts | A student misremembering the exam date must not override the syllabus |
| `forget_memory` only accepts labels shown in this turn | `chat.py` | The model can't delete something it hasn't seen |
| Memory text in prompts is fenced as data | `recall.py` formatting | Stored text is the student's own words, but it's still text going into a system prompt |

## 7. Module layout and interface

```
backend/memory/
  __init__.py      # MemoryService — the one interface agents use
  store.py         # SQLite schema, CRUD, FTS, cosine scan. No LLM
  extract.py       # extraction + summary prompt, code filters
  consolidate.py   # decision prompt, applying ADD/UPDATE/INVALIDATE/NOOP
  recall.py        # scoring, profile block, formatting for the model
  compress.py      # history building (summary + last 4 turns)
  forget.py        # decay sweep, hard delete, cascades
  worker.py        # background queue, restart recovery
```

```python
class MemoryService:
    def __init__(self, sm_home: Path, course_id: int, llm: JsonLLM,
                 embed: Callable[[str], list[float]], now: Callable[[], datetime] = utcnow): ...
    def observe_turn(self, conversation_id: str, turn_index: int) -> None       # queues a job
    def observe_session(self, turns: list[dict], at: datetime, session_id: str) -> None  # sync; eval harness
    def profile_block(self) -> str
    def recall(self, query: str, k: int = 5, include_history: bool = False) -> list[MemoryHit]
    def forget(self, memory_ids: list[str]) -> int
    def list(self, include_inactive: bool = False) -> list[dict]
    def sweep(self) -> SweepReport
```

The LLM client, the embedder, and the clock are all passed in. `chat.answer` already takes its
`search` and `provider` the same way. This means:
- Unit tests run offline, with a scripted LLM and a deterministic fake embedder.
- The benchmark runs the same code on LongMemEval without Canvas, the app, or model files beyond
  BGE.
- The evaluation can replay time.

`memory/` doesn't import `canvas.py`, `course_sync.py`, or `main.py`. That's what makes it a
platform other agents can reuse, not a chat feature.

## 8. Changes to existing code

| File | Change |
|---|---|
| `llm.py` | Add `complete_json(messages) -> dict` to `OpenAIProvider` (non-streaming, `response_format={"type": "json_object"}`) |
| `chat.py` | `answer()` gains `memory: MemoryService \| None = None`. When set: profile block in the system prompt, the `recall-0` result, the `recall_memory` and `forget_memory` tools, `[M\d+]` stripping, and history built by `memory.compress`. When `None`: behaves exactly as today |
| `main.py` | `/ask` takes `conversation_id` (conversation history plan) and calls `observe_turn` after saving. New memory endpoints (§9). The final stream event gains `memories_used: [{id, text}]` |
| `config.py` | `memory_enabled` (default: see §12) |
| `app/src/sidecar.ts`, `HomeView.tsx` | Minimum for the demo: keep the `conversation_id` from the first chunk and send it back. The full history UI stays in the conversation history plan, Tasks 4–5 |
| `indexing.py`, `generation.py`, `course_sync.py` | No change |

## 9. API

- `POST /courses/{id}/ask`
  - Optional `conversation_id`, per the conversation history plan.
  - The final `{"citations", "grounded"}` event gains `memories_used`, so the app can later show
    "Using 2 things you told me". Showing it is a responsible-AI point, not decoration.
- `GET /courses/{id}/memories?include_inactive=0|1`
  - Returns `{"memories": [{id, kind, text, importance, event_time, created_at, valid_to,
    status}]}`.
- `DELETE /courses/{id}/memories/{mid}`
  - Hard delete (§5.7). Returns `{"status": "deleted"}`, or `404`.
- `DELETE /courses/{id}/conversations/{cid}` (from the conversation history plan)
  - Also runs the memory cascade.

All of these go through `_course_selected`, like `/ask` does. Memory ids match `[\w-]+`, like
session and conversation ids.

## 10. Priorities and build order

**P0 (Sprint 5, required)**
- §4–§7, except graph expansion. Entities are still extracted and stored.
- The chat and `/ask` integration, the memory endpoints, and the minimal frontend id passing.
- The evaluation's LongMemEval sample, student-memory set, and regression run.

**P1 (if time allows)**
- Graph expansion and entity ↔ Canvas item links.
- The ablations in the evaluation spec.
- The explainer reading the profile block and the open task for its assignment.
- App events as task signals: opening "explain this assignment" records a `task` memory with no
  LLM call.

**P2 (later)**
- Cross-modal links: lecture transcript chunks linked to the slides they discuss, by embedding
  similarity within a course, stored as graph edges. Recall could then answer "Lecture 6 · 14:22
  was about slide 12 of Test-Doubles.pdf".
- A student-level memory store.
- The memory screen.

| Day | Work |
|---|---|
| Fri 9/25 | Specs; set up the environment (uv, models, OpenAI key); download LongMemEval |
| Sat 9/26 | `store`, `extract`, `consolidate`, `recall`, with offline tests first |
| Sun 9/27 | `compress`, `forget`, `worker`; evaluation harness; development runs on the oracle split |
| Mon 9/28 | Chat and `/ask` integration and the frontend id; LongMemEval test run; student-memory set; regression run |
| Tue 9/29 | Report and demo |

If P0 slips on Sunday, keep S0/S2/S3 on LongMemEval and the student-memory set, and drop S1 and
the ablations.

## 11. Decisions

| Decision | Choice | Reason |
|---|---|---|
| Where memory lives | Inside the sidecar, a `backend/memory/` package with no Canvas imports | Local-first like everything else; reusable by other agents |
| Scope | Per course | Isolation rule (design spec §5.1); no cross-course merges; free cleanup |
| Store | SQLite + FTS5 + numpy cosine | Lots of row updates, small data, no new dependency, avoids known LanceDB schema issues |
| When memory is written | Background, after the answer streams | No added latency; a failure can't break an answer |
| Extraction granularity | Per turn in the product, per session in the benchmark | Same function; a turn is the product's natural unit, and per-session keeps benchmark cost down. Recorded as a threat to validity |
| Replacing facts | Supersede with a date, don't delete | Supports "before/after" questions and an audit trail |
| Forgetting | Soft (supersede, archive) plus hard (explicit, cascades) | Relevance vs. privacy: when the student says forget, it's really gone |
| Recall | Profile block + automatic recall + tool | Preferences apply without search; automatic first call mirrors the fix chat already needed |
| Combining vector and keyword results | Rank fusion | Scores aren't comparable (learned from LanceDB hybrid) |
| Memory in answers | Never citable, markers stripped in code | Course citations must stay trustworthy |

## 12. Risks and open questions

- **Extraction attributing assistant text to the student.** This is the most likely failure;
  LongMemEval's single-session-assistant questions probe it directly. Mitigated in the prompt
  (and measured), not solved.
- **Background cost.** 1–2 extra gpt-4o-mini calls per turn. The evaluation measures cost per
  turn.
- **Untested constants.** The starting values (0.70, 0.5, the 30-day recency constant, the
  archive windows) are guesses until the evaluation calibrates them. The course cutoff went
  through the same process.
- **Memory competing with course facts.** Handled by §6's rules. The regression run checks it.
- **Open for Richa (responsible AI):**
  - Should memory be on by default, with a visible "memory is on" note? Or off until the student
    turns it on?
  - Students will mention classmates ("Priya is on my team"). Is storing names exactly as the
    student said them acceptable?
- **Open for the team:**
  - This work displaces Study artifacts (Step 11, Yongjie) from Sprint 5.
  - The team's Sprint 5 report still needs course-search precision@k compared with Sprint 3.
    That's naturally Aaron's (retrieval owner) and isn't covered here.
- **Frontend dependency.** Without the app sending `conversation_id` back, every question starts
  a new conversation. Facts still carry across chats, but compression within a chat doesn't
  happen. §8's minimal change covers the demo.

## 13. References

- Wu et al., *LongMemEval: Benchmarking Chat Assistants on Long-Term Interactive Memory*, ICLR 2025, arXiv:2410.10813.
- Chhikara et al., *Mem0: Building Production-Ready AI Agents with Scalable Long-Term Memory*, 2025, arXiv:2504.19413 (ADD/UPDATE/DELETE/NOOP consolidation).
- Rasmussen et al., *Zep: A Temporal Knowledge Graph Architecture for Agent Memory*, 2025, arXiv:2501.13956 (dated invalidation instead of deletion).
- Park et al., *Generative Agents: Interactive Simulacra of Human Behavior*, 2023, arXiv:2304.03442 (recency × importance × relevance).
- Packer et al., *MemGPT: Towards LLMs as Operating Systems*, 2023, arXiv:2310.08560 (tiered memory, summaries).
- Zhong et al., *MemoryBank: Enhancing Large Language Models with Long-Term Memory*, 2023, arXiv:2305.10250 (forgetting curve).
