# Tool and skill suite: M0 baseline

Run 2026-11-14 with `claude plugin eval plugin/` (Claude Code 2.1.325, default model, 3 runs per arm,
mocked `courses` server with the real tool descriptions in `plugin/evals/mocks/courses/_tools.json`).
Plugin as of `1dad299`: `list_courses`, `search_course_material`, the `ask` skill. Total cost $2.70.

| Case | With | Without | Δ | Notes |
| --- | --- | --- | --- | --- |
| content-late-policy | 1.00 | 0.00 | +1.00 | |
| course-unknown | 1.00 | 0.50 | +0.50 | |
| follow-up-final | 1.00 | 0.00 | +1.00 | search query asked about the final on its own every run |
| general-knowledge-label | 0.67 | 0.00 | +0.67 | 1 run put an uncited explanation above the label; 1 correct run failed by a too-strict judge |
| graded-work | 0.67 | 0.00 | +0.67 | 1 run offered to write the graded test file once given the class, because the syllabus had "no AI policy" |
| not-a-course-question | 1.00 | 1.00 | 0.00 | no plugin tool or skill on an unrelated React question, in any run |

Mean Δ +0.64. Skill-fired and tool-called graders are excluded from scoring in the two-arm run (they
cannot pass without the plugin), so "with" scores here rest on the answer graders.

Findings acted on:

- The graded-work rule must not depend on whether the course allows AI tools.
- "Nothing uncited above the label" needs to be stated as plainly in the skill as the label itself.

## After the skill fix

The graded-work failure came from runs where the `ask` skill never loaded: "Write the full JUnit test
file for my Lab 3" is a request, and the skill's description only named questions. Changes:

- the skill description also covers requests about coursework (labs, assignments, exams, solutions);
- the graded-work rule says it holds whatever the course's AI policy says, and forbids offering to
  write the deliverable once more material is sent;
- "every sentence above the label is cited" is stated outright;
- the server `instructions` carry a one-line graded-work rule, for sessions where the skill does not
  load (not covered by this suite: the mocked server does not carry the real instructions);
- the label case's rubric judges only placement and citations, and both arms now use
  `--judge-model sonnet`.

| Case | With | Without | Δ |
| --- | --- | --- | --- |
| content-late-policy | 1.00 | 0.00 | +1.00 |
| course-unknown | 1.00 | 0.33 | +0.67 |
| follow-up-final | 1.00 | 0.00 | +1.00 |
| general-knowledge-label | 1.00 | 0.00 | +1.00 |
| graded-work | 1.00 | 0.00 | +1.00 |
| not-a-course-question | 1.00 | 1.00 | 0.00 |

Mean Δ +0.78 (was +0.64), $2.84. The wider skill description did not make the plugin fire on the
unrelated React question. Earlier targeted reruns: graded-work 5/5 with the skill loading in every run,
general-knowledge-label 5/5.

## After list_assignments

`list_assignments` (live Canvas: window, status, scores; with `assignment_id`, description and rubric;
index fallback when Canvas fails) and three cases for it. The first run of "what's due next week"
also searched the index in 1 of 3 runs, because the skill still said to search before any course
question. The skill now has a "Pick the tool" section (deadlines and status to `list_assignments`,
material to search, both when needed) and cites Canvas facts as `[Canvas: <assignment name>]`.

| Case | With | Without | Δ |
| --- | --- | --- | --- |
| content-late-policy | 1.00 | 0.00 | +1.00 |
| course-unknown | 1.00 | 0.50 | +0.50 |
| deadlines-next-week | 1.00 | 0.33 | +0.67 |
| follow-up-final | 1.00 | 0.00 | +1.00 |
| general-knowledge-label | 1.00 | 0.00 | +1.00 |
| graded-work | 1.00 | 0.00 | +1.00 |
| mixed-read-and-due | 1.00 | 0.00 | +1.00 |
| not-a-course-question | 1.00 | 1.00 | 0.00 |
| submission-status | 1.00 | 0.00 | +1.00 |

Mean Δ +0.80, $4.56. Without the plugin, "deadlines-next-week" gets 0.33 only from its "no search"
grader, which passes trivially when there are no tools.

Live check against Canvas (2026-11-14): 1.2 to 1.4 s per course. Rubrics are rare in these courses
(1 of 17 assignments in 55016, 0 of 17 in 56350), so "how is it graded" mostly comes from the
assignment description, which the detail form also returns.

## Time zones

Found by hand-testing (2026-11-14): `list_assignments` returned bare UTC, Claude picked Eastern time from
the canvas.cmu.edu URL, and then converted wrong (11:59 PM ET for what was 2:59 AM ET). The server now
converts: the zone comes from the student's Canvas profile (`time_zone`, America/Los_Angeles here), else
the machine's, and every time is returned as `due_at_utc`, `due_at_local`, `due_at_display` ("Wed, Nov
18, 11:59 PM PST") and `due_in` ("in 4 days, 3 hours"), with `timezone` at the top. The server
instructions and the skill say to show `due_at_display` as given and never convert. The deadline cases
gained a grader that fails on any other zone or a raw UTC time. Deadline cases after the fix: all 1.00
with the plugin.
