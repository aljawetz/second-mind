# Quiet Ledger UI Redesign Plan

**Status:** Implemented as stacked PRs #41 to #47, one per step, each with its proof in the description. Decisions 1 to 4 were settled before starting (see below).

**Goal:** Replace the current card-and-shadow UI with the "Quiet ledger" design: ink on a blue-grey ground, flat white cards, one near-black action, blue only on sources and countdowns, red only for what is late or failed.

**Design reference:** the 22-screen canvas at https://claude.ai/artifact/VRuUcoEEsi6D7RFMovwR3Y (screens named in each step below). Dates and course data in it are examples.

**Approach:** Almost all of this is CSS. `app/src/styles.css` already routes colour, radius and type through tokens, and the components are plain class names. So the order is: tokens and fonts first, then shell by shell, touching `.tsx` only where the design changes structure (sidebar groups, title row, source rows, rail). No behaviour changes, no new dependencies except one font package.

## What changes, in one table

| Today | Quiet ledger |
|---|---|
| `--bg #F3F4F0` green-grey, white panels with 1px borders and shadows | `--ground #f2f4f7`, white cards with no border and no shadow, inset fields on `#eceef2` |
| Petrol accent on buttons, active course, footnotes | Near-black `#141414` for the one primary action, blue `#1d5fbf` only on source numbers and the due countdown |
| Plus Jakarta Sans, Public Sans, IBM Plex Mono (course codes, counts) | Geist only, tabular figures for numbers, no monospace |
| Uppercase tracked labels (`.qa-notes .kind`) | Sentence case |
| Sidebar is a bordered panel | Sidebar sits on the ground, active item is a grey fill |
| Pills for assignment status | Plain text status, red only when late or due within a day |
| Dark mode via `prefers-color-scheme` | Light only. The dark token block is removed (decision 1) |

## Decisions

1. **Light mode only (decided).** The mocks are light only, so the app ships light only. Delete the `@media (prefers-color-scheme: dark)` block in `styles.css`, set `color-scheme: light` on `:root`, and do not write dark tokens. This removes the dark pass from step 7 and one class of contrast checks. If dark mode comes back later it is a new token block, nothing else.
2. **Fonts (agreed).** `index.html` loads fonts from Google Fonts, which needs network and breaks the "everything stays local" promise on first launch offline. Bundle Geist with `@fontsource-variable/geist` (v5.3.0, OFL-1.1, checked on npm) and delete the Google Fonts links.
3. **Delivery (agreed).** Stacked PRs, one per step, each with before and after screenshots in the description (this is how the lecture speedup was done).
4. **Things in the mocks that the app does not do today (agreed).** Each is small, and each can be dropped without touching the rest:
   - quiz results list "Worth another look" (needs the missed questions' citations, already stored on each question)
   - flashcards end screen offers "Review 7 cards" (missed plus unmarked, needs a filter on the existing `order`)
   - model provider as radio rows instead of a select (same state, different control)
   - home subline shows "due Friday" only. The mock's second clause, "two of four sections have lecture material indexed", is not derivable from data we have, so it is not in the plan.
   - source rows show the label and a kind-based action ("Open" or "Play"). `Citation` has only `source_type`, `label` and `item_id`, so a separate position like "31:20 to 32:05" shows only if it is already inside `label`. Splitting it out is a backend change and is out of scope.

## Steps

Each step builds (`npm run build` in `app/`, which runs `tsc`) and runs in the real app before it merges. There is no frontend test runner in `app/`, so proof is the build output plus screenshots of the screens listed, taken from the running app. Adding a test runner is out of scope.

### 1. Foundation: tokens, fonts, base components

Canvas reference: none, this is the system under every screen.

- `app/package.json`: add `@fontsource-variable/geist`. `app/src/main.tsx`: import it. `app/index.html`: remove the three Google Fonts tags.
- `app/src/styles.css` `:root`: replace the colour tokens with the Quiet ledger set (`--ground`, `--surface`, `--raised`, `--active`, `--text`, `--muted`, `--accent` near-black, `--blue`, `--neg`, `--pos`, `--warn`). Keep the old token names as aliases for one step so nothing breaks (`--bg: var(--ground)` and so on), then delete the aliases in step 7. No migration code, per the pre-launch rule.
- Radius becomes 8 for cards and 6 for controls (`--r`, `--r-md`, `--r-sm`). Remove `--shadow`. Keep `--shadow-pop` for menus and the modal only.
- Rewrite the shared pieces everything else uses: `.btn-primary`, secondary grey button, text button, danger button, `.icon-btn`, `.pill`, form fields and `.seg`, `.panel`, `.back-link`, focus ring.
- Remove the dark `@media` block and set `color-scheme: light` (decision 1).

Proof: build passes; screenshot of the current app with the new tokens (it will look half-converted, that is expected); `grep -n "shadow\|font-family" app/src/styles.css` showing only the allowed uses.

### 2. Shell: sidebar and title row

Canvas: Home screens (sidebar and header), Manage courses (settings menu).

- `Sidebar.tsx`: brand row, near-black "New chat" button, a "Courses" group, the active course expanded with its chats, a "Recorded sessions" row with a count that expands to the session list (status dots: running, failed, done), "New session" as a text action, footer with Canvas status dot and Settings. Same props and handlers as today. The delete-chat confirm and failure text keep their behaviour and restyle only.
- `Topbar.tsx`: becomes a title row. Course code as muted text (not a boxed chip), name as a 24px title, sync status as a dot and text (`.sync`, `.sync.error`), "Course options" as text. Keep the `syncStatus` prop shape.
- `styles.css`: `.app` grid (256px sidebar on the ground, no border), `.sidebar`, `.course-btn`, `.side-*`, `.topbar*`, `.settings-menu`.

Proof: screenshots of the sidebar with no chats, with chats, with sessions expanded (one running, one failed), delete confirm, and settings menu open; sync pill in ok and error states.

### 3. Course home

Canvas: Home empty chat, Home grounded answer, Home searching and sync error, Home general knowledge and memories.

- `ChatPanel.tsx`, `Answer.tsx`: question bubble on the inset tone (no dark bubble), answer on the white card, footnote markers in blue, sources as rows under the answer (number, label, action) instead of the uppercase list. General-knowledge block as a muted inset with the sentence-case label. "Used what you told me earlier" line with the memory text. Searching and error states as plain text and an inset error box with "Try again" where the code already has a retry; no new retry logic if there is none today.
- Empty state: heading, one sentence, three suggestion rows (existing `suggestionsFor`).
- Composer: inset field with a near-black Send button.
- `HomeView.tsx`: right rail with Assignments (large day number, name, status text, countdown bar on the first item when due within 7 days, "Past and completed" toggle) and the Study panel. Subline under the title derived from `splitAssignments` only (decision 4).
- `StudyPanel.tsx`: Quiz and Flashcards rows with "Customize" and "Create", artifact rows with count, generating dot, error text, Delete.
- `assignmentStatus.ts`: keep `statusPill`, add a plain-text variant that returns the same text and a tone (`late`, `ok`, `normal`) so the rail and the assignment view share it. Remove pill classes once nothing uses them (step 7).

Proof: screenshots of all four home states, plus the assignments error state and a study item in generating and failed states.

### 4. Assignment and lecture views

Canvas: Assignment prompt, Assignment explanation, New session recording, Session notes and transcript, Session states.

- `AssignmentView.tsx`: back link, title row with due text and points, prompt card, "Explain this assignment" as the primary button, explanation as two sections (what's being asked, where to start with source rows), loading and error states. Layout per the canvas: explanation left, prompt and follow-up right.
- `NewSessionView.tsx`: recording card with red dot, timer, "Stop and process"; live transcript card with timestamps if the data has them (it is one string today, so show it as one block and skip timestamps); notes card.
- `SessionDetailView.tsx` and `SessionContent.tsx`: notes card with the indexed tag, transcript card, your-notes card, rename and delete as text actions, and the interrupted, processing and error panels.

Proof: screenshots of each status the view handles (recording, starting mic, processing, interrupted, error, done, silent) using the real statuses; a real short recording through to the done state.

### 5. Study: customize, quiz, flashcards

Canvas: Customize quiz, Quiz question answered, Quiz results, Flashcards answer shown, Flashcards end of deck.

- `StudyCustomize.tsx`: modal with `.seg` controls, topic field, sources list with group checkboxes (the indeterminate logic stays), disabled rows with their reason.
- `QuizView.tsx`: progress bar and counter, option rows with right and wrong tones plus the verdict text (colour is not the only signal), source row, "Next question" disabled until answered. Results as four stats. Optional "Worth another look" list (decision 4).
- `FlashcardsView.tsx`: flip card on white, source row, Got it / Missed it, shuffle, CSV and delete as text actions, end-of-deck stats. Optional "Review missed" (decision 4).

Proof: screenshots of every state above plus keyboard flow (space to flip, arrow keys) still working; modal focus trap still works.

### 6. Manage screens and onboarding

Canvas: Manage courses, Manage memories, Model provider, Starting up, Connect your accounts, Select your courses, Indexing your courses, Empty loading and error states.

- `ManageCoursesView.tsx`, `ManageMemoriesView.tsx`, `ModelProviderView.tsx`, `ProviderKeyFields.tsx`: list rows with text actions, inline delete confirm in the row, inline memory edit with its error text, provider choice (decision 4), GitHub device-code state.
- `StartupGate.tsx`, `OnboardingKeys.tsx`, `OnboardingCourses.tsx`, `OnboardingIndexing.tsx`: centered 560px column, cards on the ground, per-course indexing cards with progress bar, failed course with "Try again".

Proof: screenshots of a fresh first launch through to the app (new Keychain profile or a clean data folder), the indexing failure state, and the "second copy running" message.

### 7. Cleanup and audit

- Delete the alias tokens from step 1, unused pill and chip classes, uppercase and letter-spacing leftovers, any remaining `box-shadow` on resting elements, and the mono font references.
- Contrast check on the final tokens (muted text on ground and on card, blue on inset, red on inset, disabled buttons).
- Confirm the app stays light when macOS is in dark mode (native menus and scrollbars may still follow the system; check the Tauri window theme setting).
- Window-width pass at the app's minimum width (the `narrower windows` block at the end of `styles.css`).
- Reduced motion: confirm no transitions were added that ignore it.

Proof: `grep` counts before and after for `box-shadow`, `border:`, `text-transform`, `--f-mono`; contrast table in the PR description; screenshots of one screen per group, taken with macOS in dark mode to show the app stays light.

## Risks

- **Half-converted state between steps.** Step 1 changes shared tokens and will look odd until step 6. Mitigation: stacked PRs, and the aliases keep every screen readable meanwhile.
- **Contrast.** Muted `#6b6b6b` on the `#eceef2` inset is about 4.6:1, which passes for text but not for text smaller than 13px. The plan keeps meta text at 13px or larger, and step 7 re-measures.
- **Colour is not the only signal.** Late and failed items keep a text cue ("Due in 2 days", "Couldn't generate"), and quiz answers keep "Right answer" and "Not quite".
- **No automated frontend tests.** Behaviour regressions are caught by the manual checks in each step's proof. If a step touches logic (the study sources checkbox, the delete confirms), test those paths by hand and say so in the PR.
