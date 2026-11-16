# Second Mind plugin for Claude Code

Work in progress toward a release (`docs/plans/2026-11-13-claude-code-plugin.md`).

What it has:

- `.mcp.json`: the `courses` MCP server, started with `uvx` from the `second-mind-mcp` package in
  `server/` (on GitHub at the release tag; `SM_SERVER_SOURCE` overrides it). Tools: `list_courses`,
  `search_course_material`, `list_assignments`, `sync_course`, `sync_status`.
- `skills/ask`: picks the tool, cites every course fact as a link to its Canvas page, labels general
  knowledge, and doesn't do graded work.
- `evals/`: the tool and skill suite (`claude plugin eval plugin/`).

Search uses only the bge-small embedding model (no reranker). The server downloads it from Hugging Face
on first use (pinned revision, sha256-checked) into the plugin's data folder; `sm-mcp --download-model`
does the same up front.

`sync_course` indexes a Canvas course in the background (about 30 s for a small course, including the
first model download); `sync_status` reports progress. The `/second-mind:setup` skill is next.

## Try it

From the repo root, with `uv` installed:

```bash
./plugin/dev.sh
```

It runs this checkout's server and plugin with nothing else loaded. The first run downloads the
server's dependencies (about 250 MB, under a minute); later starts take about 2 seconds.

## Evaluate it

Mode `P` of `backend/scripts/ask_modes_eval.py` runs each question through `claude -p` with only this
plugin loaded, and scores it like the app's modes:

```bash
cd backend
uv run --inexact --extra mcp python3 scripts/ask_modes_eval.py --set heldout --only E,P --out <path>
```
