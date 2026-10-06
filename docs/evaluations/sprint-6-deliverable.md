# Sprint 6 deliverable: the end-to-end alpha

Richa Pragat, Lakshita Rahoria, Shatakshi Chaudhri, Aaron Weng, Yongjie Shu, Arthur Jawetz

- Raw data from the dry run: [2026-10-04-e2e-dry-run/results.json](2026-10-04-e2e-dry-run/results.json)
- Rerun it: `cd backend && uv run python scripts/e2e_dry_run.py --course <canvas id>` (macOS; see the script's header)
- Study artifacts design and earlier live runs: [docs/plans/2026-10-03-study-artifacts.md](../plans/2026-10-03-study-artifacts.md)

## Summary

Every major part of Second Mind now runs together on a student's real course. On
2026-10-04 we ran the whole chain on 49797 (Advanced AI for Industry and Society) with real Canvas
data and gpt-4o-mini:

1. sync the course;
2. ask cited questions;
3. explain an assignment;
4. record a lecture;
5. ask about what was said in it;
6. make a quiz from that week's slides plus the recording;
7. press Explain on a question.

All 24 steps worked, and every failure case we tried was refused or reported without a crash.
(The results file records the sync step as an error: the run script misread sync's one-line
reply. Calling sync again by hand returned `new: 0, failed: 0`. The script is fixed.)

The run also found where the alpha falls short. The biggest problem: a quarter of the questions
in one quiz weren't supported by the passage they cite, and the check meant to catch that missed
them. It's the first fix for Sprint 7, ahead of several smaller gaps listed below.

## 1. End-to-end integration

### What runs together

| Part | What it does | Where |
| --- | --- | --- |
| Desktop app | Tauri (Rust + React). Onboarding, course home, chat, assignments, sessions, Study panel | `app/` |
| Local backend | Python sidecar the app starts and stops; the app passes it the stored keys | `backend/main.py` |
| Canvas sync | Modules, pages, files (PDF, PowerPoint, Word, Excel, text), syllabus, assignment descriptions; only what changed is re-read | `canvas.py`, `course_sync.py`, `ingestion.py` |
| Local index | Per-course LanceDB table, local embeddings, keyword and meaning search combined | `indexing.py`, `generation.py` |
| Chat | Agent that searches the course itself, cites every course fact, labels general knowledge | `chat.py` |
| Assignment explainer | Breaks down what an assignment asks and points to material; never drafts the answer | `explain.py` |
| Session capture | Records in the app, transcribes locally (faster-whisper), indexes transcript and notes | `sessions.py` |
| Study artifacts (new) | NotebookLM-style quizzes and flashcards from chosen sources, each item cited and checked | `study.py` |
| Agent memory | Remembers what the student told it across chats, with forget and edit | `memory/` |

Only two things leave the student's machine: calls to the model provider they chose, and calls
to Canvas with their own token.

### The dry run

The run drove the real backend over HTTP, making the same calls the app makes, on a copy of the
student's data, so nothing real was changed. The study screens were also clicked through in the
app by hand; the full screen-by-screen walkthrough is the live demo.

| Step | Input | Result | Time |
| --- | --- | --- | --- |
| Canvas connection | Stored token | Course list returned, 49797 present | 0.5 s |
| Sync | 49797 | Nothing new since the last sync (confirmed by hand, see above); 27 documents indexed, grouped by Canvas week | 7.9 s |
| Cited question | "How should we choose which papers to include in a literature review?" | Answer with 3 citations (Research Study p.6–7, sample review p.4) | 4.7 s |
| Question from a Word file (new) | "Possible names for the fintech app idea, and its target audience?" | Audience answered from *Fintech App.docx*; the names were missed (see §3) | 2.4 s |
| Explain an assignment | Sprint 6 deliverable | 12-point breakdown, no drafted content; no source pointers (see §3) | 2.3 s |
| Record a lecture | 80 s of synthetic speech | Transcribed, summarized and indexed; word error rate 2.3% | 12.1 s |
| Ask about the recording | "When did the professor say the check-in moves to?" | "Thursday at 3 pm", cited *Class #1 · 0:00* | 1.3 s |
| Quiz | Week 02 sources plus the recording, topic "literature reviews and PRISMA" | 10 questions citing both the PDF and the lecture | 58.2 s |
| Explain on a quiz question | First question | Opens a chat answer, cited | 2.3 s |
| Flashcards | Word file only, easy | 10 cards from *Fintech App.docx* | 12.1 s |

The lecture-to-quiz flow is the "second brain" claim in one go: a lecture recorded minutes earlier
was searchable in chat and became quiz questions alongside the official slides.

## 2. Must-have functionality and testing

**Automated tests:** 423 backend tests pass (`uv run --group test pytest -m "not integration"`).
They cover the Canvas client, sync, extraction, indexing, chat, conversations, memory, sessions,
study artifacts and the HTTP routes, all without a network or a key. There are no frontend tests.

**The dry run** above added a normal, an edge and a failure case for each requirement, against
real services.

| Requirement | Normal | Edge | Failure | Status |
| --- | --- | --- | --- | --- |
| **FR1** Student's own Canvas token and model key, kept local | Stored token lists courses | Malformed key refused at onboarding | A well-formed but fake key is **accepted**: onboarding checks format only | Works, gap |
| **FR2** Ingest the course's content | 27 documents incl. Word and Excel | Unreadable types (video, images) listed greyed out with the reason | One failing file doesn't stop the sync; Canvas offline still lists sources (tests) | Pass |
| **FR3** Answer with citations | 3 cited sources | Answer from a Word file | Wrong citation numbers are dropped in code (tests) | Pass, one miss |
| **FR4** Say when the course doesn't cover it | Off-topic question: "not mentioned", no citations | | | Pass |
| **FR5** Record, transcribe locally, notes | 80 s lecture: 2.3% WER, askable with a timestamp | 10 s of silence: finishes with an empty transcript and **no message** | Non-audio upload: session marked failed, but shows a **raw decoder error** | Partial |
| **FR6** Index isolated per student | One folder per OS user, one table per course (tests) | | | Pass |
| **FR7** Grades fetched live, never stored | Assignment list with submission status live from Canvas | Asking for a grade: "couldn't find", nothing indexed | Only assignment descriptions are indexed (code) | Pass |
| **FR8** Explain an assignment, never draft | 12-point breakdown, no drafted text | | | Pass, gap |
| **FR9** Study artifacts (Should have) | Quiz and flashcards, cited | Recording and Word file as sources | Invalid options 400, other course 404, bad progress 400 | Pass, quality gap |

**Not tested yet:**
- **A real lecture recorded by a person.** The speech here was synthetic and clean, so 2.3% WER
  says nothing about a classroom.
- Microphone permission denied (only reachable in the app).
- The schedule-based auto-start for FR5, which isn't built.
- Re-testing multiple courses (FR10); it was covered in Sprint 5's evaluation across three courses.

### Are the quiz questions grounded?

We graded the dry run's 10 quiz questions by hand: does the passage each one cites support its
answer?

| Result | Count | Questions |
| --- | --- | --- |
| Supported | 6 | e.g. "Which is a key step in the PRISMA selection process?" (lecture) |
| Not supported: model's own knowledge | 3 | "What does PRISMA stand for?" (the lecture never spells it out); "What is a systematic review?" and "a critical component of a systematic review" (cited page doesn't say) |
| Misleading | 1 | Presents PICO as part of the PRISMA process; the lecture names them separately |

Every item passes a second model check before the student sees it. In this quiz the check
dropped 4 of 15 candidates but let these 4 through. The answers are plausible, so a student
wouldn't notice; that is exactly the risk design spec §8 names. With a sample of 10 questions,
"6 of 10" is a direction, not a rate.

## 3. Integration assessment

### Failures and gaps found

| # | Problem | Seen | Severity |
| --- | --- | --- | --- |
| 1 | The study check passes questions answered from the model's own knowledge | 4 of 10 quiz questions | High |
| 2 | Flashcards from a whole course fell short: 15 of 20, after the check dropped 31 of 48 drafts | Dry run | Medium |
| 3 | Onboarding accepts a well-formed but wrong key; it fails later, in chat or sync | Dry run, `validate_credential` | Medium |
| 4 | The explainer's "Where to start" was empty for the Sprint 6 assignment | Dry run | Medium |
| 5 | Chat missed the first section of the Word file (the app's possible names) | Dry run | Medium |
| 6 | A silent recording finishes as an empty session with no explanation | Dry run | Low |
| 7 | A file that isn't audio shows the decoder's raw error, including an internal file path | Dry run | Low |
| 8 | The test suite occasionally aborts *after* passing (`recursive_mutex lock failed`), a native shutdown race | Once in about 10 runs | Low |
| 9 | `npm run tauri dev` runs the packaged backend; after a backend change the app shows "no such route" until it's rebuilt | Development | Medium for the team |

Found and fixed during the sprint:
- A student's Word and Excel files weren't indexed at all.
- Six issues from CodeRabbit's review of the study feature, such as out-of-order progress saves
  and a dropped question blocking its own retry.

### Bottlenecks

| Operation | Time | Why |
| --- | --- | --- |
| Quiz | ~60 s | Two model calls (write, then check), plus a second round when the check drops too many |
| Flashcards, whole course | ~45 s | Same, on about 30k tokens of course text |
| Lecture processing | 12 s for 80 s of audio | Transcription, AI summary and indexing; scales with length, so a 50-minute lecture is minutes |
| Sync with nothing changed | 8 s | Every module page is fetched again to compare; Canvas gives module items no timestamp |
| Chat answer | 1–5 s | Fine |

### Technical debt

- **No frontend tests.** The four frontend fixes from code review are covered only by hand.
- **Key validation is still a format check.** The code says a later step would add a real call,
  which never happened.
- **The same small model writes and checks study items**, so it shares its own blind spots.
- **Pages that are mostly code** (Research Study p.6 is a Python script with a paragraph after it)
  are cited as if they were prose.
- **The packaged backend must be rebuilt by hand** after every backend change.

### Usability problems

- Without a topic, quizzes lean on the course's longest documents (a sample proposal and a sample
  literature review).
- A quiz takes a minute with only "Generating…" to show for it.
- Choose sources lists all 14 assignment pages, which are rarely what a student studies from.
- Silent and failed recordings don't say what went wrong (above).

### Next sprint, in priority order

1. **Make the study check reliable.** Require each item's answer to be quoted from its passage and
   reject it otherwise, or check with a stronger model. Measure it on a hand-graded set of about 50
   items, and compare against NotebookLM on the same material.
2. **Check keys with a real call at onboarding**, as design spec §5.4 requires.
3. **Record a real lecture** and measure transcription accuracy and speed. Then build the
   schedule-based prompt that completes FR5.
4. **Fix explainer pointers and the Word-file retrieval miss.**
5. **Clear messages for silent and failed recordings.**
6. **Put the alpha in front of students** (Sprint 7's user validation), starting with the
   lecture-to-quiz flow.
