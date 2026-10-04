# Conversation History Implementation Plan

> **For agentic workers:** Steps use checkbox (`- [ ]`) syntax for tracking. Run `uv run pytest tests/ -q` from `backend/` after every backend task.

**Goal:** A student can see the Q&A conversations they've had with a course, reopen one, read its answers and citations again, keep asking in it, and delete it.

**Why this is needed today:** `HomeView.tsx` keeps chat turns in local React state. Switching course, opening an assignment, opening a session, or restarting the app throws every answer away. `/ask` itself writes nothing to disk.

**Architecture:** The backend owns persistence, the same way it already owns sessions. A new `backend/conversations.py` stores one JSON file per conversation under the course directory. `/ask` takes an optional `conversation_id`, streams it back in its first chunk, and appends the finished turn to that conversation once streaming completes. Three new read/delete endpoints serve the list and detail. On the frontend, the active conversation id moves up into `AppShell`, and the chat panel gets a "New chat" button and a "History" list.

**Tech stack:** Python stdlib (`json`, `uuid`, `threading`), existing `ThreadingHTTPServer` handler, React/TypeScript.

**Status (2026-09-26):** Tasks 1-3 are built, as part of agent memory
(docs/superpowers/specs/2026-09-25-agent-memory-design.md), and so is Task 4's `conversationId`
argument with the minimal `HomeView` change. Task 4's list/get/delete client functions and Tasks 5-6 are
not. Two changes from this plan:
- `conversation_id` rides on the first stream event, whatever it is: since the tool-loop chat,
  that's a `{delta}`, not `{citations, grounded}`.
- The turn is saved just before `{"done": true}`, not after. The app sends the next question with
  the id as soon as it sees `done`.

`/ask` and the endpoints are tested in-process in `tests/test_ask_memory.py`, instead of the manual
`curl` check.

## Decisions

| Decision | Choice | Reason |
|---|---|---|
| Where history lives | Backend, on disk | Matches sessions, survives restarts, and `courses.delete_course` already `rmtree`s the course dir, so cleanup on course removal is free. Webview `localStorage` would not be cleaned up and is not visible to the backend. |
| Who writes a turn | The `/ask` handler, after the stream finishes | One request per question (no second "save" call that can fail on its own), and the saved answer is exactly what was streamed. |
| Unit of storage | One JSON file per conversation | Conversations are small (text + citation labels). A file per conversation keeps delete trivial and avoids a new SQLite schema. |
| Title | First question, trimmed to 60 chars | No extra LLM call. Rename can come later. |
| Follow-up context | Already handled: `/ask` takes `history` (see `backend/chat.py`) | Reopening a saved conversation should send its saved turns as `history`, so follow-ups keep working. |
| History UI placement | Chat panel header ("New chat" + "History" dropdown) | History is per course and the chat lives on `HomeView`. The sidebar already carries the course → sessions tree; adding a second list there crowds it. Easy to move later. |
| Failed turns | Not saved | A turn that errored before streaming (bad key, missing model) has no answer worth keeping. A stream cut off by a client disconnect is also skipped. |

## On-disk format

```
~/.secondmind/courses/{course_id}/conversations/{conversation_id}.json
```

```json
{
  "conversation_id": "c-3f9a1b2c4d5e",
  "title": "What does the rubric say about test coverage?",
  "created_at": "2026-09-23T14:05:12Z",
  "updated_at": "2026-09-23T14:09:40Z",
  "turns": [
    {
      "question": "What does the rubric say about test coverage?",
      "answer": "The rubric gives 20 points for... [1]",
      "citations": [{"source_type": "file", "label": "Rubric.pdf · p.2", "item_id": "file:123"}],
      "grounded": true,
      "asked_at": "2026-09-23T14:05:12Z"
    }
  ]
}
```

`conversation_id` is `c-` plus 12 hex chars from `uuid4`. It matches the existing `[\w-]+` route pattern, which also blocks path traversal.

## API

- `POST /courses/{id}/ask` body gains optional `conversation_id`. The first NDJSON chunk gains `conversation_id` (a new one when none was sent). Unknown id → `404 not_found` before streaming starts.
- `GET /courses/{id}/conversations` → `{"conversations": [{conversation_id, title, updated_at, turn_count}]}`, newest `updated_at` first.
- `GET /courses/{id}/conversations/{cid}` → the full file above, or `404`.
- `DELETE /courses/{id}/conversations/{cid}` → `{"status": "deleted"}`, or `404`.

All four go through `_course_selected` like `/ask` does.

---

### Task 1: `backend/conversations.py`

**Files:** create `backend/conversations.py`, create `backend/tests/test_conversations.py`

**Interface:**
- `new_conversation_id() -> str`
- `exists(sm_home, course_id, cid) -> bool`
- `append_turn(sm_home, course_id, cid, turn: dict) -> None`: creates the file on the first turn (title from the question, `created_at`), otherwise appends and bumps `updated_at`.
- `list_conversations(sm_home, course_id) -> list[dict]`: summaries only, sorted by `updated_at` desc, `[]` if the dir doesn't exist.
- `get_conversation(sm_home, course_id, cid) -> dict | None`
- `delete_conversation(sm_home, course_id, cid) -> None`: raises `KeyError` if missing (same contract as `sessions.delete_session`).

A module-level `threading.Lock` guards the read-modify-write in `append_turn`, same reasoning as `sessions._counter_lock`: `ThreadingHTTPServer` can run two `/ask` requests for one conversation at once. Write via temp file + `os.replace` so a crash mid-write can't leave half a JSON file.

- [x] Write tests first: first turn creates file and title; title truncation at 60 chars; second turn appends and bumps `updated_at`; list is newest-first and per course; get/delete of a missing id; list on a course with no conversations dir.
- [x] Implement until they pass.

### Task 2: persist turns from `/ask`

**Files:** modify `backend/main.py`

- [x] Read optional `conversation_id` from the body. If given and `not conversations.exists(...)`, return `404` before any other work. If absent, `conversations.new_conversation_id()`.
- [x] Add `conversation_id` to the first chunk: `{"conversation_id", "citations", "grounded"}`.
- [x] Accumulate streamed deltas into `answer` (or use `NOT_COVERED_MESSAGE` for the ungrounded path).
- [x] After writing `{"done": true}` and the terminating chunk, call `conversations.append_turn(...)` with question, answer, citations, grounded, `asked_at`.
- [x] Wrap the streaming loop so a `BrokenPipeError`/`ConnectionResetError` (student navigated away mid-answer) returns without saving, instead of logging a traceback.
- [x] Keep the handler thin: the only new logic is id resolution and one `append_turn` call. Behaviour is covered by Task 1's tests; `/ask` itself needs a live LLM and stays covered by `scripts/generation_smoke_test.py`.

### Task 3: list/detail/delete endpoints

**Files:** modify `backend/main.py`

- [x] Add `CONVERSATION_LIST_PATH = ^/courses/(\d+)/conversations$` and `CONVERSATION_DETAIL_PATH = ^/courses/(\d+)/conversations/([\w-]+)$`.
- [x] Wire `GET` list, `GET` detail, `DELETE` detail next to the session handlers, same 404 shapes.
- [x] Manual check with `curl` against a running sidecar: ask twice with the returned id, list, get, delete, list again.

### Task 4: frontend client

**Files:** modify `app/src/sidecar.ts`

- [x] `askQuestion(courseId, question, conversationId | null, onEvent)`; event type gains `conversation_id?: string`.
- [ ] Add `ConversationSummary`, `Conversation`, `ConversationTurn` types.
- [ ] Add `listConversations`, `getConversation`, `deleteConversation`, following `listSessions` / `getSessionDetail` / `deleteSession`.

### Task 5: lift chat state and add history UI

**Done in the UI redesign (branch `ui/notebook-redesign`), with two changes from this plan:**
the chat list lives in the sidebar under the active course (the redesign gave the sidebar room
for it), and deleting a chat uses an inline confirm instead of `window.confirm`. `HomeView` now
hosts a `ChatPanel`, which is remounted by an `AppShell` key when the student picks a chat, and
loads the saved chat only on mount.

**Real finding:** the shipped `HomeView` read `conversation_id` from the `done` line, but
`main.py` sends it on the first line only. So every question started a new saved conversation.
`ChatPanel` now takes the id from the first line and reuses it for follow-ups.

**Files:** modify `AppShell.tsx`, `HomeView.tsx`, `styles.css`

- [ ] `AppShell` holds `conversationId: string | null` and `conversations: ConversationSummary[]`. Load the list on course change (same effect as `refreshSessions`). Reset `conversationId` to `null` on course change.
- [ ] `HomeView` takes `conversationId`, `conversations`, `onSelectConversation(id | null)`, `onConversationSaved(id)`, `onDeleteConversation(id)`.
- [ ] When `conversationId` changes to a non-null id, `HomeView` loads it with `getConversation` and maps saved turns to `ChatTurn` with `status: "done"`. `null` clears the thread. Guard against the in-flight turn being wiped: skip the reload when the id change came from this component's own first answer.
- [ ] `send()` passes the current id. On the first chunk's `conversation_id`, call `onConversationSaved(id)` so `AppShell` stores it; refresh the list when the turn's `done` arrives (the file exists only after that).
- [ ] Chat header: "New chat" (disabled while busy or when the thread is empty) and a "History" dropdown listing title + relative date, active one highlighted, a delete action per row using the same `window.confirm` pattern as `SessionDetailView`. Close on outside click / Escape like the settings menu in `Sidebar.tsx`.
- [ ] Empty state in the dropdown: "No past conversations yet."
- [ ] Coming back to Home from an assignment or session keeps the active conversation because the id now lives in `AppShell`.

### Task 6: docs

- [ ] `docs/architecture/data-model.md` §1: add `conversations/` to the tree.
- [ ] `docs/architecture/overview.md` §2: document the `/ask` change and the three new endpoints.
- [ ] `docs/architecture/implementation-plan.md`: add a step entry for this feature with any real findings from testing.

## Edge cases to check by hand

- Reopening a conversation whose citation points at a session that was later deleted: clicking it should land on `SessionDetailView`'s not-found state, not crash.
- Two quick questions in a brand new chat: the second must reuse the id from the first chunk, not create a second conversation. Disabling input while busy (already the case) covers this.
- Course removed in Manage Courses: its conversations go with the course dir.
- Ungrounded answers are saved and shown with no sources, same as live.

## Out of scope (follow-ups)

- Renaming conversations.
- Search across conversations.
- Cross-course history view.
