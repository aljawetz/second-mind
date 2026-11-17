# Sprint 9 deliverable: Second Mind beta and independent testing

Richa Pragat, Lakshita Rahoria, Shatakshi Chaudhri, Aaron Weng, Yongjie Shu, Arthur Jawetz

- Sprint notes: [docs/sprints/sprint-09.md](../sprints/sprint-09.md)
- Plan most of this sprint came from: [docs/plans/2026-11-09-rag-course-gaps.md](../plans/2026-11-09-rag-course-gaps.md)
- Pull requests: #55–#63, #65, #66 (all merged)

The outside tester's runned
## Beta system completeness

Second Mind is a desktop study assistant for Canvas courses. The app (Tauri/Rust + React) starts a
local Python backend, which syncs the student's courses, indexes them on the student's machine, and
answers questions with an agent that searches the course and cites its sources. Only the model call
and the Canvas sync leave the machine.

This sprint we found eight gaps, and closed them one PR at a time.

### What the beta does now

| Area | What changed | Result |
| --- | --- | --- |
| Follow-up questions (#55) | A follow-up like "and the final?" is rewritten to stand alone, then searched once | First search finds the fact on 25 of 26 follow-up turns, up from 17 (`sprint9-chat`: 14 chats, 2 courses); 2.8 s a turn against 2.9 s |
| Memory (#56) | Memory evaluation built on LongMemEval (`scripts/memory_eval.py`); better extraction, search over past chats, 10 memories recalled instead of 5 | Questions about what the assistant said before: 0–2 of 10 → about 6 of 10 |
| Default model (#56) | `gpt-5-mini` replaces `gpt-4o-mini` | 49.5–51.5 of 58 against 42–43 (four runs each); course chat is slower, 11.7 s a turn against 2.6 s |
| Course sync (#63) | Reads the Files tab, links in every page, syllabus, assignment, announcement and discussion, and the announcements and discussions themselves, not only Modules | Files indexed: 18-658 0 → 37, 56350 7 → 29, plus 13 announcements; 0 failures |
| Listing questions (#63) | New `list_course_items` tool lists a course's modules, files, announcements and discussions | Expected items named in answers: 52 → 93 of 138 (announcements 3 → 13 of 13) |
| Large files (#65) | PDFs over 150 pages and text over 450,000 characters are synced as a labeled preview; files over 50 MB are skipped; "Sync whole file" in Manage courses | 18-658's first sync: 14.4 → 4.5 minutes |
| Junk chunks (#66) | Chunks under 8 characters or under 25% letters are left out of the index | Not measured separately |
| Graded-work guard (#62) | A small classifier on the local embedding flags requests to do graded work; a flagged turn gets a stricter rule | 26 of 32 held-out misuse requests caught, 4 false alarms in 65; clear refusals in chat 23 → 29 of 32; "when is homework 2 due?" still answered 6 of 6 |
| Interface (#57, #60, #61) | Helpful / Not helpful buttons with a note; Auto / Light / Dark look; reopened chats keep their "Used what you told me earlier" line | |
| Error handling (#58) | A model reply that isn't usable JSON is asked for once more | Memory, consolidation, quizzes and flashcards no longer fail silently |

The Must Have workflow from the design spec (§5.4) is: connect keys → select courses → index →
ask questions with citations. All four steps work end to end on real Canvas courses (18-658 and
56350).

### Known limits

- Course chat on `gpt-5-mini` takes about 11.7 s a turn, four times slower than before. We kept it
  for the better answers.
- The first sync of a large course still takes minutes. Showing names and outline first, then
  content in the background, is an agreed follow-up.
- A list inside one long page (for example, a reading list in a syllabus) can still be missed.
  A tool that reads a whole page by name is an agreed follow-up.
- We decided to index everything the student can open, including exam and quiz text. The
  graded-work guard, not the index, keeps the assistant from doing graded work.

## Independent testing and defect resolution

### How the test is run

An outside tester, someone not on the team, installs the beta from the release and runs the core
workflow alone: connect their Canvas token and model key, pick courses, wait for indexing, then
ask questions. No developer changes code during the test. The tester rates answers with the
Helpful / Not helpful buttons (#57), and `GET /courses/{id}/feedback` lists the thumbs-down turns
for us to review afterwards.

### outside tester's run
Followed only the README, on a fresh clone of main (`61547b4`), macOS 26.0. It
used its own data folder and did not change any code. We used it to catch problems before a person
hits them.

| Step | Result |
| --- | --- |
| Fresh clone + `./scripts/bootstrap.sh` | Worked, 177 s; 785 backend tests passed |
| App build and tests | Worked |
| Connect keys, list courses | 11 courses listed |
| Sync 18-658 | 81 items, 0 failed; first sync 290 s, repeat sync 29 s |
| Ask 10 questions | 9 of 10 correct; follow-up date right but project name wrong |
| Rate an answer Not helpful | Listed by `GET /courses/{id}/feedback` |
| Restart the backend, including mid-sync | Courses, chats and feedback kept |

The 10 questions covered due dates, two taught concepts, a follow-up, readings, announcements,
something the course doesn't cover (answered "not in the course" plus labelled general knowledge),
and a request to write a graded report (refused, with an outline and an offer to review a draft).
Answers took 6–24 s to start.

| # | Problem found | Severity | Status |
| --- | --- | --- | --- |
| 1 | The key check accepted any 20 characters as a Canvas token, and fake OpenAI keys | High | Fixed in #69: a real call to Canvas and the provider |
| 2 | Asking about a course that was selected but never synced dropped the connection | High | Fixed in #69: answers "not found" |
| 3 | A follow-up got the date right but named the wrong project | Medium | Open |
| 4 | Near-duplicate memories, and memories unrelated to the question shown as used | Medium | Open |
| 5 | Repeat sync shows no progress for 29 s; skipped images are only in the log | Medium | Open |
| 6 | `backend/README` setup notes are out of date; `SM_HOME` and `SM_PORT` not documented | Medium | Open |
| 7 | Setup docs don't mention the signing certificate or the third local model (about 357 MB) | Low | Open |
| 8 | A harmless "max diff: nan" warning while converting the reranker; 2 `npm audit` warnings | Low | Open |

### Defects found and fixed this sprint

Found by the team during the sprint, before the outside run:

| Defect | Fix |
| --- | --- |
| Sync missed every file outside Modules (none of 18-658's 46 readings were searchable) | #63 |
| Reopened chats lost their memories-used list | #60 |
| The no-search baseline crashed on `gpt-5-mini`, which rejects a temperature setting | #59 |
| The grades filter dropped harmless memories ("lost 10 pounds") | #56 |
| A model reply that wasn't usable JSON made memory, quizzes and flashcards fail silently | #58 |
| The first sync of 18-658 took 14.4 minutes because of large textbooks | #65 |

### Checking the answer grader

Our evaluations use a gpt-4o judge, so we checked it (#59). One person hand-graded 20
`sprint9-chat` turns blind. The judge picked the better answer 20 of 20 times and gave the same
grade on 32 of 40; every disagreement had the judge one step stricter than the person. We keep the
judge for comparisons against a baseline, not as an absolute score.

## Deployment and documentation

- **Install the beta:** download the `.dmg` from the
  [v0.2.0 release](https://github.com/aljawetz/second-mind/releases/tag/v0.2.0) and follow
  [README → Download (macOS)](../../README.md#download-macos). It is built from main by
  `release.yml` and has everything from #55–#66 and #69. The build is unsigned, so macOS needs
  `xattr -cr` or Open Anyway the first time.
- **Run from source:** [README → Quickstart from source](../../README.md#quickstart-from-source-macos):
  clone, then `./scripts/bootstrap.sh`, then `npm run tauri dev`. The bootstrap checks
  prerequisites, installs dependencies and fetches the local models. The AI pre-test followed it on
  a fresh clone and it worked (bootstrap 177 s, all tests passing).
- **Configuration:** onboarding asks for the school's Canvas URL, a Canvas API token, and an
  OpenAI, DeepSeek or GitHub Copilot key, kept in the macOS Keychain. Since #69 the token and key
  are checked with a real call to Canvas and the provider, so a wrong one is caught at onboarding.
  Billed evaluation scripts can use their own OpenAI key (`scripts/eval_key.py`), separate from the
  app's.
- **Docs:** [README](../../README.md) for users, [CONTRIBUTING.md](../../CONTRIBUTING.md) for
  developers, and the sprint notes in [docs/sprints/sprint-09.md](../sprints/sprint-09.md).
- **Reproducing the numbers:** each PR lists the commands that reproduce its results.
- **Course text stays private:** the repository is public, so evaluation outputs that quote course
  material are kept out of git and described in each report instead.
- **Tests:** on main after #69 (2026-11-16), 796 backend tests pass (9 skipped), up from 536 at
  the end of Sprint 8. The app builds (`npm run build`) and its 5 interaction tests pass
  (`npm test`).
