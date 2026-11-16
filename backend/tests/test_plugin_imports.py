"""The plugin's server must import without the app's chat stack (plan
docs/plans/2026-11-13-claude-code-plugin.md, "MCP tools": no tool calls an
LLM). The installed package (`plugin/server`) leaves openai and the app's
chat modules out, so importing any of them on the plugin's path would crash
a student's server at startup.

Runs in a subprocess with those modules blocked, so it doesn't matter that
this repo's venv has them installed.
"""

import os
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent

# The app-only modules: LLM providers, chat, memory, and their SDKs.
BLOCKED = ["openai", "llama_index.llms.openai", "providers", "llm", "copilot_llm", "chat", "memory", "copilot",
           "faster_whisper", "github_signin"]

PROBE = f"""
import importlib.abc, sys
BLOCKED = {BLOCKED!r}
class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path=None, target=None):
        if any(name == b or name.startswith(b + ".") for b in BLOCKED):
            raise ImportError(f"plugin path imported app-only module {{name}}")
sys.meta_path.insert(0, Block())
import mcp_server, course_sync, course_items, generation, assignments, citation_links, query_dates, model_download, sync_jobs
mcp_server.build_server()
print("ok")
"""


def test_server_imports_without_the_apps_chat_stack(tmp_path):
    # An empty models folder, as on a student's machine before setup downloads
    # the models: the server must still start (and say what's missing later).
    env = {**os.environ, "SM_MODELS_DIR": str(tmp_path / "models"), "SM_HOME": str(tmp_path / "home")}
    result = subprocess.run([sys.executable, "-c", PROBE], cwd=BACKEND, capture_output=True, text=True, timeout=120, env=env)

    assert result.returncode == 0, result.stderr[-3000:]
    assert result.stdout.strip().endswith("ok")
