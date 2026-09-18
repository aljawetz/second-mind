#!/usr/bin/env bash
# One-shot dev environment setup — collapses backend/README.md's multi-step
# setup (uv sync, model conversion, model fetch, npm install) into a single
# command, contribution-and-distribution-plan.md step 3.
#
# macOS only, matching the rest of this project today (Windows/Linux are
# explicitly out of scope for the first release — same doc, step 5).

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

missing=()
command -v uv >/dev/null 2>&1 || missing+=("uv (https://docs.astral.sh/uv/getting-started/installation/)")
command -v node >/dev/null 2>&1 || missing+=("node (https://nodejs.org, or: brew install node)")
command -v npm >/dev/null 2>&1 || missing+=("npm (comes with node)")
command -v tesseract >/dev/null 2>&1 || missing+=("tesseract (brew install tesseract)")
if [ ! -x "$HOME/.cargo/bin/cargo" ] && ! command -v cargo >/dev/null 2>&1; then
  missing+=("rust (https://rustup.rs)")
fi

if [ "${#missing[@]}" -gt 0 ]; then
  echo "Missing prerequisites:" >&2
  for m in "${missing[@]}"; do echo "  - $m" >&2; done
  exit 1
fi

echo "==> Backend: installing Python dependencies (uv sync --all-groups)"
cd "$repo_root/backend"
uv sync --all-groups

echo "==> Backend: generating the local embedding model (one-time, needs network access to Hugging Face)"
uv run python3 scripts/convert_embedding_model.py

echo "==> Backend: fetching the session-transcription model (one-time, needs network access to Hugging Face)"
uv run python3 scripts/fetch_whisper_model.py

echo "==> Backend: running the test suite to confirm the environment is sound"
uv run pytest tests/ -q

echo "==> Frontend: installing npm dependencies"
cd "$repo_root/app"
npm install

cat <<'EOF'

==> Done. Start the app with:

    cd app
    PATH="$HOME/.cargo/bin:$PATH" npm run tauri dev

First launch of a freshly built binary can take a few minutes while macOS
Gatekeeper scans it (implementation-plan.md step 1) — this is expected, not
a hang.
EOF
