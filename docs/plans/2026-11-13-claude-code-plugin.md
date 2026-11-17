# Second Mind as a Claude Code plugin

Draft, 2026-11-13. Revised the same day: the plugin is the product, not a second front end. Revised
again after reading main as of PR #57 (follow-up rewrite, past-chat search, answer feedback,
`gpt-5-mini` default, and the RAG gaps plan `2026-11-09-rag-course-gaps.md`). Revised 2026-11-14 after
the M0 spike was built: live Canvas data versus the index (Decision 15), and an evaluation of the tool
and skill surface itself (Decision 16, "Tool and skill evaluation").

## Why

Students will not download another app to study. They will add a plugin to the Claude Code they
already use. The backend already does the hard parts locally (Canvas sync, ingestion, hybrid
retrieval with a reranker, citations), so the plugin is a thin layer over the same code.

Claude Code is the LLM. The plugin supplies retrieval and tools, and Claude answers, writes quizzes,
flashcards and mind maps. The student pays with the Claude subscription they already have.

That last sentence is an assumption, not a fact: Claude Code needs a paid Claude plan. The Sprint 9
beta asks every tester whether they use Claude Code and which plan they have (see Timeline).

## Product direction

- **The plugin is the product.** It is what we publish, demo and point students to. A student
  installs only the plugin. Nothing in the plugin depends on the app being installed.
- **The app is frozen after the Sprint 9 beta.** It stays working for the final presentation, with no
  new features. Shared backend modules can change, but the app must still build and run after each
  change.
- **Sprint 9 beta (2026-11-17) runs on the app as is.** Plugin work starts 2026-11-18. The beta
  results, including the thumbs-up and thumbs-down feedback from PR #57, are the baseline the plugin
  is compared against.
- The repo (`aljawetz/second-mind`) is public, so the marketplace and the release assets work for
  anyone.

## What ships

One plugin, installed with `/plugin marketplace add aljawetz/second-mind` then
`/plugin install second-mind@second-mind`.

| Piece | What it is |
| --- | --- |
| MCP server (stdio, Python) | Tools over the existing backend modules, see below |
| Skills | `setup`, `ask`, `explain-assignment`, `quiz`, `flashcards`, `mindmap`, `study-plan` |
| Hook | `SessionStart`: incremental sync in the background, never blocks the session |
| Marketplace | `.claude-plugin/marketplace.json` at the repo root, plugin source in `plugin/` |

### MCP tools

Organized around what a student asks (Decision 17), not around the backend. A student's question comes
down to one of four needs, and each need has one tool:

| Student need | Tool | Backed by | Source | Notes |
| --- | --- | --- | --- | --- |
| What does the course say? | `search_course_material(course_id, query, k)` | `indexing`, `reranker`, `generation.HybridRetriever` | Index | Built (M0). Returns up to `k` chunks (default 5, at most 10) with citation labels, later with the Canvas URL (Decision 11), plus a sync-in-progress note when the index is partial |
| What do I have to do? | `list_assignments(course_id, days, only_unsubmitted, assignment_id)` | `canvas.list_assignments`, `canvas.get_assignment` | Live Canvas | Without `assignment_id`: deadlines and submission status in a window, filtered, sorted and capped in code like the app's `show_deadlines`. With it: one assignment's description, **rubric**, submission and score. Rubrics are not indexed, so this is the only place they come from. Falls back to indexed due dates, marked as possibly stale, when Canvas cannot be reached |
| What changed? | `get_announcements(course_id, days)` | new, in `canvas.py` | Live Canvas | Cancelled classes, room changes, extensions. Nothing reads announcements today: not `canvas.py`, not the index |
| What is in the course, and where? | `get_course_outline(course_id, week)` | `canvas.get_course_structure`, `study.list_sources` | Synced Canvas structure plus the index catalog | Modules grouped by week, each item with its type, Canvas link and whether it is indexed. Replaces `list_sources` and `list_course_items` ("what's for week 5?", "where are the lecture 7 slides?", "quiz me on this week") |
| Which course? | `list_courses()` | `indexing`, `sync`, `canvas.list_courses` | Index tables, sync records, Canvas names | Built (M0). Maps "my testing class" to an id |

Maintenance tools are used by the `setup` skill and the `SessionStart` hook, not by a student's
question, and their descriptions say so:

| Tool | Backed by | Notes |
| --- | --- | --- |
| `sync_course(course_id)` | `course_sync.sync_course` | Starts a background job, returns a job id. Fills the index |
| `sync_status(job_id)` | new, thin | Progress from the generator's events |
| `add_file(course_id, path)` | `ingestion`, `indexing` | A PDF the student downloaded outside Canvas. Writes to the index |

Open:

- **Calendar events.** Exam dates may live in the syllabus, in Canvas calendar events, or both. If the
  calendar matters, it goes in `list_assignments` or `get_course_outline`, not a tool of its own.
- **Grades** (`get_grades`, a course total). Useful ("what do I need on the final?") but sensitive; a
  product call. Per-assignment scores already arrive with each submission, see below.

What the Canvas API gives without extra calls (checked against the Canvas API docs, 2026-11-14):
`GET /courses/:id/assignments` returns `rubric` (criteria with points and ratings), `rubric_settings`
and `use_rubric_for_grading` on every assignment that has a rubric, so `list_assignments` needs no
second request for rubrics. `include[]=submission`, which `canvas.list_assignments` already sends, adds
the student's own `score` and `grade`. Announcements need one new call, `GET /announcements` with
`context_codes[]=course_<id>`, whose default window is the last 14 days.

Names and descriptions here are a first guess: Decision 16 decides them by measurement. The earlier
`get_assignment` became the `assignment_id` form of `list_assignments`, and `list_sources` and
`list_course_items` became `get_course_outline`.

No tool calls an LLM. `llm.py`, `providers.py`, `copilot_llm.py`, `credentials.py` (provider keys) and
`github_signin.py` are not used by the plugin. **This is not true at import level today:**
`generation.py:16` and `explain.py:29` import `providers`, which imports `openai` at module level
(`providers.py:18`), and `study.py` imports `generation`. Without `openai` installed, every tool
except `list_courses` fails on import. M1 splits the retrieval half of `generation.py`
(`HybridRetriever`, `rerank`, citations) from `build_query_engine`, or makes the `providers` import
lazy, so the `mcp` extra in Decision 4 can leave `openai` out.

## Decisions

All decided unless marked open.

1. **Data home.** The plugin keeps its index, manifests and models in `${CLAUDE_PLUGIN_DATA}`
   (`~/.claude/plugins/data/<id>/`), which survives plugin updates and is removed on uninstall. The
   server reads it as `SM_HOME`, set in `.mcp.json` `env` as `"SM_HOME": "${CLAUDE_PLUGIN_DATA}"`.
   Setting `SM_HOME` explicitly overrides it, which is how M0 reads the index the app already built
   in `~/.secondmind`. No index is shared with the app.
2. **Single writer.** Claude Code starts one MCP server per session, so two open sessions mean two
   servers. A lock in `SM_HOME` allows one sync at a time. It is an `fcntl.flock` on a lock file, not a
   PID file: the server is killed when its session closes, often mid-sync, and the OS releases a
   `flock` when the process dies, so a dead session never leaves a stale lock. The `SessionStart`
   hook exits at once when the lock is held. Searches do not take the lock. A killed sync resumes
   cleanly because the manifest commits per item (`sync.py:88`). Check in M1 that LanceDB reads stay
   consistent while a sync writes.
3. **Canvas token and URL.** Declared in `plugin.json` `userConfig`: `canvas_base_url` (string) and
   `canvas_token` (string, `sensitive: true`, stored in the system keychain by Claude Code). They
   reach the server through `env` with `${user_config.canvas_token}`, and the hook through
   `CLAUDE_PLUGIN_OPTION_CANVAS_TOKEN`. Both need an env path in the backend:
   - the token is read from `keyring` today (`credentials.py`, `canvas.py:36`);
   - the base URL is read from `config.json` today (`canvas.py:43`).

   In both cases the env value wins when set.
4. **How the server is launched.** `uvx` from a git tag, never from `main`:
   `uvx --from "sm-backend[mcp] @ git+https://github.com/aljawetz/second-mind@<tag>#subdirectory=backend" sm-mcp`.
   Installed plugins are copied into a cache and paths with `..` are rejected (plugins reference), so
   a relative path into `backend/` cannot work. The backend becomes an installable package with an
   `sm-mcp` entry point. The `mcp` extra holds only what search and sync need: no `faster-whisper`,
   `github-copilot-sdk`, `llama-index-llms-openai` or `openai` (which needs the import split above).
   Each plugin release bumps `version` in `plugin.json` and the tag together.

   The first `uvx` run downloads onnxruntime, lancedb, pyarrow, pandas and llama-index-core, which
   can take longer than Claude Code waits for an MCP server to start. `setup` and the `SessionStart`
   hook both warm the `uvx` cache first (`uvx ... sm-mcp --version`), and M1 measures the cold start
   on a clean machine.
5. **Where models live.** BGE and the reranker live in `SM_HOME/models`. They are produced today by
   converting to ONNX locally (`scripts/convert_embedding_model.py`, `scripts/convert_reranker_model.py`,
   the `convert` dependency group), which needs torch, so a student cannot build them. We publish the
   exact `.onnx` files the app uses as GitHub Release assets with sha256 checksums, and the plugin
   downloads and verifies them on first run. `MODEL_DIR` is relative to the module file today
   (`embeddings.py:25`, `reranker.py:27`), which points inside site-packages once installed. It becomes
   configurable, defaulting to `backend/models` so the app is unaffected.
6. **Prerequisites.** Only `uv` is required (it fetches Python 3.13 itself). Tesseract is optional: it
   is only used to OCR scanned PDFs, so `setup` reports that it is missing, prints the `brew install`
   line and continues.
7. **Memory use with several sessions.** Accept one server per session. Models load on the first
   search, not at startup, so a session that never asks about a course costs almost nothing. A
   shared daemon is only worth building if this hurts in practice.
8. **How `ask` searches.** The app always makes the first search itself before the model writes
   anything: the student's exact words, or for a follow-up a stand-alone rewrite
   (`chat.standalone_query`, PR #55, `chat.py:470`). Claude Code decides on its own whether and what
   to search. The `ask` skill and the server `instructions` say: search before answering any course
   question, and for a follow-up, search with a stand-alone version of the question. Claude sees the
   whole conversation, so it does the rewrite itself and no extra LLM call is needed. M0 measures how
   often it actually searches first.
9. **Graded-work rule.** The "don't do graded work" rule travels in the skills and server
   `instructions`, as a prompt, the same as in the app today. The classifier guard in RAG gaps task 7
   is app-side and does not apply to the plugin. If the plugin needs it later, it fits a
   `UserPromptSubmit` hook that adds a stricter instruction, but that loads the embedding model on
   every prompt, so it is not in v1.
10. **Left out of v1.** Lecture capture and transcripts (they come from the app), memory
    (`recall_memory`), past-chat search (`search_past_chats`, PR #56), conversation history (Claude
    Code has its own), answer feedback (PR #57), the `grounded` flag, and provider choice. Lecture
    support can come back later as `add_file` for an audio file, transcribed with Whisper.
11. **Citations link to Canvas.** In the app a citation is a link, built in the frontend from the
    Canvas origin and the item id (`app/src/citations.ts`, `/files/{id}` or `/pages/{url}`). In a
    terminal, "lecture3.pdf, p.12" alone is hard to open. The server builds the same URL in Python
    from `canvas_base_url` and returns it with each chunk, next to the label from
    `generation.citation_for`, so Claude cites with a clickable link.
12. **Where the plugin runs.** An installed plugin is active in every Claude Code session, including
    sessions where the student is coding something unrelated. So:
    - the `SessionStart` hook skips the sync when the last one finished less than 6 hours ago (the
      last sync time `list_courses` already reports), so Canvas is not called on every session;
    - tool descriptions, server `instructions` and skill descriptions stay short, since they are in
      the context of every session.

    Open: whether the plugin works outside the terminal (the Code tab in the Claude desktop app).
    Many students who do not program would use it there. Checked in M1 and written into the README.
13. **Index version.** After M3 the plugin has real users, and a plugin update can change chunking
    (RAG gaps task 3 drops junk chunks and graded quiz text). `SM_HOME` stores an index version. On a
    mismatch the server deletes the index and manifests and runs a full sync. No migration code, the
    same rule as the app.
14. **Canvas errors.** A 401 from Canvas (token expired or revoked) becomes one clear message from
    `sync_status`, `setup` and the hook: "Your Canvas token no longer works. Run `/config` and paste a
    new one." It is never a stack trace or an empty result.
15. **Live Canvas data versus the index.** Structured, per-student or time-sensitive data is read live
    from Canvas through our own server: assignments, due dates and submission status first
    (`list_assignments`, with the rubric for one assignment), announcements (`get_announcements`), and
    a course grade total later if the product call says so. The index holds what the course
    material says (slides, readings, syllabus text, pages, assignment descriptions) and answers it by
    search. Reasons, from the M0 code and data:
    - The index is a snapshot. Course 55016 was last synced 2026-10-26, so on 2026-11-14 a new or moved
      assignment is invisible to search.
    - The index has no submission status. It stores each description plus one "Due ... Worth N points"
      line (`course_sync.schedule_line`). `canvas.list_assignments` returns `submitted`, `late` and
      `missing` with `include[]=submission`.
    - "What is due next week?" is a filter over records, not a similarity search. Search returns the top
      5 to 10 chunks and can miss items, which is why the app needed `chat.expand_relative_dates` and
      why RAG gaps task 8 calls listing questions unanswerable from five results.
    - The app already made this choice: `show_deadlines` in the generative UI plan reads Canvas live.
    - Canvas cannot search the text inside PDFs and slides, so content stays indexed, with page and
      slide numbers for citations, local and fast (0.3 to 0.4 s per search in M0).

    The live call goes through our server, not a third-party Canvas MCP: one install and one token for
    the student, a few tools in every session's context instead of dozens (Decision 12), and no write
    tools (the canvas-mcp server tried locally exposed 96 tools, including bulk grading, deleting
    assignments and sending messages). `canvas.py` already handles pagination, 429 retries and 403/404
    fallbacks. When Canvas cannot be reached (offline, Decision 14's 401), `list_assignments` answers
    from the indexed due dates and says they may be out of date.
16. **The tool and skill surface is measured, not assumed.** Which tools exist, their names and
    descriptions, the server `instructions`, and each skill's description are all prompts that decide
    whether Claude calls the right thing. Each change to them runs the suite in "Tool and skill
    evaluation" below, and a tool or skill that the suite shows makes no difference is cut.
17. **Tools follow the student's four needs.** Walking through a student's week (the question list in
    "Tool and skill evaluation") showed that the first tool list followed the backend: sync jobs,
    sources, files. Those answer none of a student's questions, while three common needs had no tool:
    rubrics ("how is Task 4 graded?"), announcements ("is class cancelled?") and the week structure
    ("what did we cover in week 5?"). So each student need gets one tool (the first table under "MCP
    tools"), and maintenance tools are kept out of the question flow. The question list was judged
    representative of what students ask (Arthur, 2026-11-14), so no count of saved chats is run first;
    the Sprint 9 beta's questions are added to the suite as they come in.

## Evaluation setup

Facts from the RAG gaps plan that M0 and M4 depend on:

- **Harness.** `backend/scripts/ask_modes_eval.py`. It drives `chat.answer()` in process, so it needs a
  new mode that runs each case through `claude -p --plugin-dir plugin/` with the MCP tools allowed
  (`--allowedTools "mcp__plugin_second-mind_<server>__*"`, the name Claude Code gives plugin MCP tools). Without that flag the tool calls are denied and the score
  drops for a reason unrelated to quality.
- **Judge.** `gpt-4o`, the same as Sprint 8 and the memory evaluation. It is not a Claude model, so
  there is no self-grading bias. Sprint 8 called it too noisy to trust, so retrieval-level numbers
  ("first search finds the fact", "any search finds it") count more than judge grades. The MCP server
  logs every query it receives, so these can be scored for the plugin the same way.
- **Baseline.** The app on current main, not the numbers in the Sprint 8 report: the default model is
  now `gpt-5-mini` (PR #56) and follow-ups are rewritten (PR #55). The baseline is rerun on the same
  machine and index as the plugin run.
- **Sets.** Only courses 55016 and 56350 are indexed locally, and nobody can sync 18-654 (55710) any
  more, so 8 of the 13 `sprint8-chat` cases cannot run. The usable sets are `heldout`,
  `sprint8-test` (single questions) and `sprint9-chat` (follow-ups, written for the two local
  courses).
- **Frozen sets run once.** The rule in the RAG gaps plan is that frozen sets run once, when the
  design is settled. M0 tunes and checks on `heldout` only. `sprint8-test` and `sprint9-chat` run in
  M4.
- **Confound.** M0 changes both the model and the pipeline. If the plugin scores lower, rerun the app
  side with its search results handed to Claude through the same tool, to tell the two apart.
- **Mode P isolation (M0).** `ask_modes_eval.py --only P` runs `claude -p --plugin-dir plugin/
  --setting-sources "" --tools Skill`, allows only the plugin's tools, and sets
  `ENABLE_CLAUDEAI_MCP_SERVERS=false`. Without that env var the student's claude.ai connectors (Gmail,
  Drive, ...) load into every run, at about 8x the tokens. `--strict-mcp-config` cannot be used: it
  also drops the plugin's own server. The appended system prompt names the course, as the app's course
  picker does, and pins "today" to `EVAL_TODAY`. A search of another course is counted
  (`wrong_course_search_count`), not scored.
- **Deadline questions.** Questions such as "what is due next week?" are scored against a saved Canvas
  snapshot (the `list_assignments` response at a fixed date), replayed to the tool, because live Canvas
  changes daily and results would drift between runs.

## Tool and skill evaluation

`ask_modes_eval.py` asks whether answers are right. This suite asks an earlier question: does Claude
call the right tool and skill, with a sensible query, and does it leave them alone when they do not
apply (Decision 16)? It uses `claude plugin eval` with the cases in `plugin/evals/`. Each case is a
prompt a student would type plus graders:

- `tool_used` with `input_match`: the right tool was called, with arguments that make sense (the right
  `course_id`, a stand-alone query on a follow-up).
- `tool_used` with `min: 0` and `max: 0` and `arm: both`: a tool or skill was not called.
- `tool_order`: for example `list_courses` before `search_course_material` when no course is named.
- `llm` rubrics: only for refusal and labeling behavior (graded work, general knowledge).

The MCP tools are mocked (`plugin/evals/mocks/courses/`), with `_tools.json` saved from the real server
so Claude sees the real names, descriptions and schemas. Search mocks return fixed chunks, so the suite
needs no index, no Canvas token and no OpenAI key, and runs in CI. Each case runs 3 times by default,
plus the same runs without the plugin, whose difference (`Δ`) is what the plugin adds.

Case groups. The example prompts are the student questions that shaped Decision 17, and the Sprint 9
beta's real questions are added as they come in:

| Group | Example prompt | Passes when |
| --- | --- | --- |
| Content | "What does the syllabus say about late work in Software Testing?" | `search_course_material` called, `list_assignments` not |
| Deadlines | "What's due next week?" | `list_assignments` called with a sensible `days`, and no search for dates |
| Mixed | "What do I need to read before the Task 3 class, and when is it due?" | both tools called |
| Assignment detail | "What exactly do I hand in for Task 4, and how is it graded?" | `list_assignments` with `assignment_id` (for the rubric), search optional |
| Submission status | "Did I submit the Task 3 report? Is anything missing?" | `list_assignments`, no search |
| Announcements | "Is class cancelled tomorrow?", "Did the prof move the deadline?" | `get_announcements` called |
| Week structure | "What did we cover in week 5?", "Where are the slides for lecture 7?" | `get_course_outline` with the week, search optional |
| Planning | "What should I work on this weekend?" | `list_assignments`, then search for the top items |
| Course unknown | "When is the final exam?" | `list_courses` called, then Claude asks which course or picks the one the question names |
| Follow-up | history "When is the midterm?", then "and the final?" | search query mentions the final exam on its own |
| Graded work | "Write my Task 4 deliverable" | no full solution (`llm`), concept help offered |
| Not a course question | "Fix this TypeError in my React app" | no Second Mind tool or skill called (Decision 12: the plugin is active in every session) |
| Skill trigger | course questions phrased without naming the plugin | the `ask` skill fires |

What the suite decides, each by running it on two variants of the plugin and comparing scores:

- **Which tools to keep.** Remove one (for example `list_courses`, by putting course ids in the server
  `instructions`) and see whether scores drop.
- **Whether the `ask` skill is needed**, or the server `instructions` alone are enough. Skill-only and
  instructions-only variants against both.
- **Names.** For example `search_course_material` against `search_course`, and `list_assignments`
  against `get_deadlines`. Claude sees `mcp__plugin_second-mind_courses__<tool>`, so the server name
  is part of the name too.
- **Descriptions.** Short against long, since every description is in the context of every session
  (Decision 12). The shortest one that keeps the scores wins.

A variant is a copy of `plugin/` with one change, run with the same cases and `--model` pinned, so a
model rollout is not mistaken for a plugin change. Results go in `docs/evaluations/2026-11-plugin-surface/`.

## Tests

The RAG gaps rule holds here too: tests first, then the code. Each milestone adds its tests to
`backend/tests/` and they run with the existing suite.

- **MCP server.** Each tool answers over stdio with a valid MCP response. Nothing but protocol goes
  to stdout (a test fails on any stray `print`). Sync-in-progress note on a missing and on a partial
  table.
- **Lock.** Two processes start a sync at once: one runs, the other gets "sync already running". A
  process killed mid-sync leaves no lock behind.
- **Installed package.** In CI, install `sm-backend[mcp]` into a fresh venv and import every module
  the tools use. This catches the `providers` / `openai` import before a student does.
- **Config and errors.** Env values for the Canvas token and URL win over keyring and `config.json`.
  A Canvas 401 gives the message in Decision 14. An index version mismatch triggers a full sync.
- **Citations.** The Canvas URL for a file and for a page match what `app/src/citations.ts` builds.
- **`list_assignments`.** Window filter, sort by due date, cap, undated assignments last, submitted ones
  left out unless asked, the same cases as `show_deadlines`. Canvas mocked with `respx`. Offline and 401
  fall back to the indexed due dates with the "may be out of date" note.
- **`get_announcements` and `get_course_outline`.** The day window and the week filter, an item that is
  in Canvas but not indexed shown as such, Canvas mocked with `respx`, the same fallback note offline.
- **Tool and skill suite.** `claude plugin eval plugin/` runs in CI with mocked tools, `--model`
  pinned, and the same threshold as the local runs.

## Milestones

### M0. Spike (built 2026-11-13, branch `feat/plugin-m0-spike`)

Goal: find out whether answers in Claude Code are as good as the app's before building anything else.

Status: built ahead of the 11-18 start. The server, the `ask` skill, the plugin folder, mode P and their
tests are in. Smoke runs of P on two `heldout` questions searched first, fired the skill and found the
gold source on the first search. The heldout run against mode E (needs the OpenAI eval key) is the
remaining step, and the exit below is still open.

- `backend/mcp_server.py` with `list_courses` and `search_course_material` only, with `SM_HOME`
  pointed at the index the app already built.
- Move all logging to stderr. On stdio, stdout is the protocol channel, and
  `course_sync.py:252` prints to stdout today.
- An `ask` skill that carries the citation rules from `SYSTEM_PROMPT` in `chat.py` and the search
  rule in Decision 8.
- Load it with `claude --plugin-dir` and ask real course questions.
- Add the `claude -p` mode to `ask_modes_eval.py` and run `heldout` against the app baseline (see
  Evaluation setup).

Exit: on `heldout`, facts found by search and judge grades are not below the app's beyond the noise
seen across repeated runs, Claude searches before answering on every course question, first search
under 10 s, later ones under 2 s. If quality drops, find out why before M1.

### M1. Packaging, sync and setup

Packaging moves here from M3, because the M1 exit test (a clean machine) needs it.

- Split `generation.py` so retrieval does not import `providers` (see MCP tools).
- Backend as an installable package with the `mcp` extra and the `sm-mcp` entry point (Decision 4).
- Models published as release assets, downloaded and checked on first run (Decision 5).
- `sync_course` as a background job with `sync_status`. Do not run it inside one MCP call: the first
  sync takes minutes and will hit the call timeout.
- `search_course_material` says "sync in progress, N of M items" while a course is being indexed.
  This covers both cases: the table does not exist yet (the app returns empty today on
  `TableNotFoundError`, `main.py:923`, which Claude would read as "the material does not say"), and
  the table exists but is partial, where results are real but incomplete.
- `userConfig` for the Canvas URL and token, read through env (Decision 3).
- `setup` skill: check prerequisites, warm the `uvx` cache, Canvas connection, model download, pick
  courses, first sync, with progress shown.
- `SessionStart` hook for incremental sync, skipped within 6 hours of the last one (Decision 12). The
  manifest hashes make it a no-op most days.
- Sync lock (Decision 2), index version (Decision 13), Canvas 401 message (Decision 14).
- Canvas URLs in search results (Decision 11).
- `list_assignments`, read live from Canvas with the indexed fallback, including the `assignment_id`
  form with the rubric (Decision 15). It needs the env path for the Canvas token above.
- `get_announcements`, live, with a new `canvas.list_announcements` (Decision 17).
- The tool and skill suite in `plugin/evals/` with mocked tools: the content, deadlines, mixed, course
  unknown, follow-up and not-a-course-question groups, run in CI (Decision 16).
- Try the plugin in the Code tab of the Claude desktop app (Decision 12, open).

Exit: a clean machine with only Claude Code and `uv` goes from install to a first cited answer using
only `setup`, and the citation link opens the right file in Canvas. The cold start of the MCP server
is measured and stays under Claude Code's startup timeout.

### M2. Study skills

- `ask`, `explain-assignment`, `quiz`, `flashcards`, `mindmap`, `study-plan` as skills. If time runs
  short, `mindmap` and `study-plan` are cut first.
- `get_course_outline`, from the Canvas module structure and the index catalog. The study skills use it
  to pick "this week's" files (Decision 17).
- Port the grounding rule from `study.py`: every item names the chunk it came from, and an item the
  chunk does not support gets dropped. Do the check as a second pass in the skill, with a subagent
  given only the item and its chunk and told not to search. A subagent can still call tools, so this
  is an instruction, not isolation. The method matches Sprint 6 but the model does not, so the
  numbers are compared as "same method, different model".
- Outputs are files in the student's working directory (Markdown, CSV for flashcards, Mermaid or
  HTML for mind maps).
- Make Claude call the tools on its own: tool names and descriptions, the server `instructions`,
  and skill descriptions that trigger on course questions without the student typing a command. These
  are settled by the tool and skill suite, not by judgment: run the variants it lists (keep or cut each
  tool, skill or instructions only, names, short or long descriptions) and keep the winners.
- The `ask` skill and the server `instructions` say which tool answers what: deadlines, status and
  rubrics go to `list_assignments`, recent changes to `get_announcements`, "which week / where is it" to
  `get_course_outline`, and what the material says to `search_course_material`.
- Add a trigger case per new skill, and a "not a course question" case that none of them fires on.

Exit: each skill run once on a real course, quiz and flashcard groundedness measured the same way as
in `2026-10-03-study-artifacts.md`. The tool and skill suite passes, and every kept tool and skill has a
variant run showing the scores drop without it.

### M3. Distribution

- `marketplace.json`, `plugin.json`, `.mcp.json`. `claude plugin validate --strict` passes.
- README leads with "Install as a Claude Code plugin". The app moves to a short section further down.
- Test on a second machine and with one person outside the team who has not seen the repo.

Exit: that person completes install, setup and one cited question without help.

### M4. Evaluation, docs and final presentation

- `sprint8-test` and `sprint9-chat`, run once, for both the app and the plugin. Written up next to
  the Sprint 8 and Sprint 9 reports.
- If RAG gaps task 6 (hand-graded sample, judge agreement) is done, its grading method is used here.
- Privacy note in the README: course content goes through Anthropic via Claude Code. The Canvas
  token and the index stay on the student's machine.
- Final presentation demos the plugin. The app is shown as the earlier prototype that the plugin
  grew out of.

## Risks

| Risk | Mitigation |
| --- | --- |
| Few students have Claude Code or a paid Claude plan | Ask every Sprint 9 beta tester before plugin work starts |
| Quality drops because Claude sees raw chunks instead of the app's pipeline | M0 comparison on `heldout`, same judge, retrieval-level numbers first |
| Claude answers without searching | Search rule in `ask` and the server `instructions`, measured in M0 |
| The `mcp` extra fails on import | Split `generation.py` in M1, test the installed package, not the repo venv |
| First `uvx` run is slower than the MCP startup timeout | Cache warm-up in `setup` and the hook, measured on a clean machine in M1 |
| First sync is slow and looks hung | Background job, progress in `sync_status`, clear message in `setup` |
| Install friction now decides adoption, since the plugin is the only way in | Only `uv` required, Tesseract optional, M3 outside tester |
| Two sessions sync at once and corrupt the index | `flock` sync lock (Decision 2) |
| The plugin only works in the terminal, and most students do not use one | Try the desktop app in M1 (Decision 12) |
| A plugin update leaves an index built with old chunking | Index version, full sync on mismatch (Decision 13) |
| An expired Canvas token looks like empty course material | Clear 401 message (Decision 14) |
| Model files differ from what the index was built with | One published set of files, checksum on download |
| A push to `main` breaks every installed plugin | Install from a tag (Decision 4) |
| Shared backend changes break the app before the final presentation | Build and run the app after each change to a shared module |
| Deadline answers come from a stale index | `list_assignments` reads Canvas live (Decision 15) |
| Canvas is slow, rate-limited or unreachable when a deadline question comes in | 429 retries in `canvas.py`; offline or 401 falls back to indexed due dates with a "may be out of date" note |
| Claude calls the wrong tool, or calls the plugin during unrelated work | Tool and skill suite with routing and "not a course question" cases, in CI (Decision 16) |
| Tool descriptions grow until they crowd every session's context | The suite's short-against-long variants; shortest description that keeps the score wins |
| Thirteen days is not enough for M0 to M4 plus the RAG gaps tasks for the final | See Timeline, open |

## Timeline

The final is due 2026-12-01 (RAG gaps plan). That leaves 2026-11-18 to 2026-11-30 for M0 to M4, with
Thanksgiving on 2026-11-26.

- Until 2026-11-17: Sprint 9 beta on the app. No plugin work. The beta survey adds two questions: do
  you use Claude Code, and which Claude plan do you have.
- 2026-11-13: M0 built (ahead of plan). 2026-11-18: M0's heldout run against the app, and the exit.
- 2026-11-19 to 11-21: M1, including `list_assignments` and the first tool and skill suite.
- 2026-11-22 to 11-24: M2.
- 2026-11-25 to 11-27: M3, outside tester.
- 2026-11-28 to 11-30: M4 and the presentation.

**Open:** RAG gaps tasks 5 to 8 were also planned as evidence for the final. This timeline has no
room for them next to the plugin. Proposal: task 6 (a grader you can trust) is kept, since M4 needs
it; task 8 is covered by `list_assignments` (deadlines) and `get_course_outline` (files, pages and
lectures by week); tasks 5 (rest of the memory
evaluation) and 7 (classifier guard) are dropped, since memory and the guard are not in the plugin.

## Not in scope

- Lecture recording and live transcription in Claude Code.
- Windows and Linux.
- New features in the app.
