# Sprint 9 — Beta Release and Independent Testing

**Type:** Team · **Due:** 2026-11-17 · **Points:** 100 · **Status:** In progress (this "What we did" section is a draft)

## Purpose

Turn the development prototype into a system that someone outside the development team can
realistically use.

## Requirements

| Requirement | What Must Be Demonstrated | Weight |
| --- | --- | --- |
| Beta System Completeness | Deliver an integrated beta with reliable Must Have functionality, appropriate interface/API, backend, AI/data components, error handling, and deployment environment | 50% |
| Independent Testing and Defect Resolution | At least one person outside the development team executes the core workflow without developers modifying code during the test; document problems and resolve the highest-priority defects | 30% |
| Deployment and Documentation | Provide a reproducible deployment/execution process, repository, dependencies/configuration, and concise user/developer documentation | 20% |

## Deliverable

Beta system, updated GitHub repository, deployment instructions, and concise independent-test
report.

## Relevant scope

The onboarding flow in [the design spec](../specs/2026-09-14-second-mind-design.md) §5.4 (connect keys →
select courses → index → land in app) is exactly the "someone outside the team can install this"
test this sprint requires.

## What we did

Eleven PRs (#55–#63, #65, #66), most from the RAG gaps plan
([`docs/plans/2026-11-09-rag-course-gaps.md`](../plans/2026-11-09-rag-course-gaps.md)): eight gaps found by
comparing Second Mind with NVIDIA's "Building RAG Agents with LLMs" course. Merged: #55–#63. Open for review:
#65, #66.

### Beta system completeness

- **Follow-up questions (#55, merged).** A follow-up like "and the final?" is rewritten to stand alone before
  the first search, and searched once. On the new frozen `sprint9-chat` set (14 chats, 26 follow-up turns,
  courses 18-658 and 56350), the first search finds the fact on 25 of 26 turns, up from 17, at 2.8 s a turn
  against 2.9 s.
- **Memory (#56, merged).** The memory evaluation planned in Sprint 5 is built (`scripts/memory_eval.py`, on
  LongMemEval). What it found is fixed or added: a grades filter that dropped "lost 10 pounds", a better
  extraction prompt, search over the student's past chats (questions about what the assistant said: 0–2 of 10
  → about 6 of 10), and recall of 10 memories instead of 5.
- **Default model `gpt-5-mini` (#56, merged).** It scored 49.5–51.5 of 58 against 42–43 for `gpt-4o-mini`
  (four runs each). The cost: course chat is about four times slower (11.7 s a turn against 2.6 s).
- **Course sync reads the whole course menu (#63, merged).** The sync only read Modules, so none of 18-658's
  46 readings were searchable (they are links in its pages and syllabus). It now also reads the Files tab,
  links in every page, syllabus, assignment, announcement and discussion, plus announcements and discussions
  themselves. Files indexed: 18-658 0 → 37, 56350 7 → 29, plus 13 announcements; 0 failures.
- **Listing questions (#63, merged).** A `list_course_items` tool lists a course's modules, files,
  announcements and discussions. Expected items named in answers: 52 → 93 of 138 over 8 listing questions
  (announcements 3 → 13 of 13).
- **Large files wait for the student (#65, open).** A PDF over 150 pages is synced as a labeled preview of its
  first 150 pages, any other file with more than 450,000 characters of text as a preview of that length, and a
  file over 50 MB not at all. Manage courses has a "Sync whole file" button for each. 18-658's first sync took
  4.5 minutes instead of 14.4; syncing one textbook whole later took 147 s.
- **Junk chunks dropped (#66, open).** Chunks under 8 characters or under 25% letters are left out of the
  index (task 3). The plan's other half, keeping exam and quiz text out, was dropped: the decision is to index
  whatever the student can open.
- **Interface.**
  - Helpful / Not helpful buttons with an optional note on each answer, kept locally (#57, merged).
  - A light look by day and a soft dark look by night, with an Auto / Light / Dark switch (#61, merged).
  - Reopened chats keep their "Used what you told me earlier" list, now folded into one line (#60, merged).
- **Error handling (#58, merged).** A model reply that isn't usable JSON is asked for once more, so memory,
  consolidation, quizzes and flashcards no longer fail silently.

### Independent testing and defect resolution

- **Feedback for the test (#57).** The outside tester can flag answers, and `GET /courses/{id}/feedback`
  lists the thumbs-down turns for review.
- **Defects found and fixed this sprint:**
  - the sync missing files outside Modules (#63);
  - reopened chats losing their memories list (#60);
  - the no-search baseline crashing on `gpt-5-mini`, which rejects a temperature (#59);
  - the grades filter dropping harmless memories (#56).
- **Answer grading checked (#59, merged).** One person hand-graded 20 `sprint9-chat` turns blind. The gpt-4o
  judge picked the better answer 20 of 20 times and gave the same grade on 32 of 40; every disagreement had
  the judge one step stricter. The judge is kept as is, for comparisons against a baseline.
- **Graded-work guard (#62, merged).** A small classifier on the local embedding catches 26 of 32 held-out
  misuse requests, with 4 false alarms in 65 (2 in 113 real Sprint 8/9 turns). A flagged turn gets a
  stricter rule. In chat, graded by hand: clear refusals 23 → 29 of 32, while "when is homework 2 due?"
  still gets its date 6 of 6.

### Deployment and documentation

- **Beta release v0.2.0 (#70).** The [v0.2.0 release](https://github.com/aljawetz/second-mind/releases/tag/v0.2.0)
  is the macOS `.dmg` built by `release.yml` from main, with everything from #55–#66 and #69. The
  install steps are in the [README](../../README.md#download-macos): the build is unsigned, so macOS
  needs `xattr -cr` or Open Anyway the first time.
- **Running from source.** The [README quickstart](../../README.md#quickstart-from-source-macos) is clone, then
  `./scripts/bootstrap.sh`, then `npm run tauri dev`. The bootstrap checks prerequisites, installs
  dependencies and fetches the local models.
  An AI agent followed it on a fresh clone and it worked (bootstrap 177 s, all tests passing).
- **Configuration.** Onboarding asks for the school's Canvas URL, a Canvas API token, and an OpenAI,
  DeepSeek or GitHub Copilot key, kept in the macOS Keychain. Since #69 the token and key are
  checked with a real call to Canvas and the provider, so a wrong one is caught at onboarding.
- **Docs.** [README](../../README.md) for users, [CONTRIBUTING.md](../../CONTRIBUTING.md) for developers, and
  the concise deliverable [docs/evaluations/sprint-9-deliverable.md](../evaluations/sprint-9-deliverable.md).
- **Reproducible evaluations.** Each PR lists the commands that reproduce its numbers. Billed evaluation
  scripts can use their own OpenAI key (`scripts/eval_key.py`), separate from the app's.
- **Course text stays local.** The repo is public, so eval outputs that quote course material are kept out
  of git and described in each report instead.

### Not done yet (due 2026-11-17)

- **The outside tester's run** of the core workflow, and the independent-test report.
- **Re-syncing courses** after #63, #65 and #66, which picks up everything #63 finds.
- **Agreed follow-ups:**
  - the rest of a faster first sync: names and outline first, then content in the background;
  - a tool that reads a whole page by name, for lists inside one long page.

### Tests

On main after #69, 796 backend tests pass (9 skipped), up from 536 at the end of Sprint 8. The app builds
and its 5 interaction tests pass.
