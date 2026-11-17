# Task 2: local answer feedback

Implements task 2 of `2026-11-09-rag-course-gaps.md`.

## Design

Finished, saved chat answers have Helpful and Not helpful buttons. Clicking
the selected rating removes it. Either rating permits an optional note of
up to 500 characters, saved explicitly. Pending writes disable the controls;
failed writes retain the last saved rating and display an inline error.
Reopening a conversation restores its feedback. No feedback is sent to a
model or an external service.

Each saved turn optionally has `feedback: {rating: "up" | "down", note:
string, updated_at: string}`. Removing a rating removes this field. Legacy
turns need no migration. Conversation order and memory progress are unchanged.
All feedback writes share the conversation store's existing lock and atomic
file replacement, so appending a turn or updating memory cannot lose feedback.

Turns are append-only, so their zero-based saved index is stable. The store
returns that index when appending (or `None` if the chat was deleted), and
the final stream event includes `turn_index` only after a successful save.
The UI uses that index rather than its rendered position: failed answers
remain visible but are not in the saved array. Loaded chats use array indices.

`POST /courses/{course}/conversations/{id}/turns/{index}/feedback` accepts
`{rating: "up" | "down" | null, note?: string}` and returns `{feedback: object
| null}`. A null rating clears feedback. Invalid input is 400; missing courses,
chats or turns are 404. `GET /courses/{course}/feedback` returns `{turns: [...]}`
for thumbs-down turns only, newest feedback first, including conversation ID,
title, turn index, the question, answer, citations and feedback for review.

## Implementation and verification

- Write storage and real HTTP tests first: save, replace, clear, reload,
  validation, missing targets, legacy chats, course filtering, ordering,
  concurrent appends/memory progress, and saved indices in streamed answers.
- Implement in `backend/conversations.py` and `backend/main.py`; run the
  focused tests, then the full backend suite.
- Extend `app/src/sidecar.ts`, add `AnswerFeedback.tsx`, wire saved indices
  and loaded feedback in `ChatPanel.tsx`, and reuse the existing action styles.
- Check actual rendered interactions: both ratings, note persistence, clearing,
  failure feedback, and no controls on streaming/failed answers. Capture
  screenshots of unrated, up and down states using synthetic course content.
- Run `npm run build`, review the final diff, document evidence, and open a
  task-2-only PR against main. Retrieval and generation behavior are unchanged,
  so no answer-quality improvement or eval claim is made.

## Result

Implemented and independently reviewed. The full backend suite passed 593
tests with 9 skips; the five frontend interaction tests and production build
passed. Screenshots and verification limits are recorded in
[`docs/evaluations/answer-feedback/README.md`](../evaluations/answer-feedback/README.md).
