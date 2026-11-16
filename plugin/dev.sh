#!/usr/bin/env bash
# Start Claude Code with this checkout's plugin and server (not the release on
# GitHub), and nothing else: no other plugins, no claude.ai connectors.
# Models come from backend/models until setup downloads them (next step).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export SM_SERVER_SOURCE="$ROOT/plugin/server"
export SM_MODELS_DIR="${SM_MODELS_DIR:-$ROOT/backend/models}"
export ENABLE_CLAUDEAI_MCP_SERVERS=false
uvx --from "$SM_SERVER_SOURCE" sm-mcp --version >/dev/null  # warm uvx's cache, so the server starts in time
exec claude --plugin-dir "$ROOT/plugin" --setting-sources '' "$@"
