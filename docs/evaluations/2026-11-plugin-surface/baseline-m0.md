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
