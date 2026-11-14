# Second Mind plugin for Claude Code (M0 spike)

This is the spike from `docs/plans/2026-11-13-claude-code-plugin.md`. It is not installable yet: the
MCP server runs from `../backend` with `uv`, so it only works from a checkout of this repo. Packaging
(`uvx` from a git tag) is M1.

What it has:

- `.mcp.json`: the `courses` MCP server (`backend/mcp_server.py`) with `list_courses` and
  `search_course_material`.
- `skills/ask`: search first, cite every course fact with its source label, label general knowledge,
  and don't do graded work.

It reads the index the app already built in `~/.secondmind` (set `SM_HOME` to read another one), so
sync your courses in the app first.

## Try it

From the repo root, with `uv` installed:

```bash
cd backend && uv sync --inexact --extra mcp && cd ..
claude --plugin-dir ./plugin
```

Then ask a course question, or run `/second-mind:ask When is the final exam?`. Run `/mcp` to check that
`plugin:second-mind:courses` is connected.

## Evaluate it

Mode `P` of `backend/scripts/ask_modes_eval.py` runs each question through `claude -p` with only this
plugin loaded, and scores it like the app's modes:

```bash
cd backend
uv run --inexact --extra mcp python3 scripts/ask_modes_eval.py --set heldout --only E,P --out <path>
```
