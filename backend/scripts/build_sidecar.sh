#!/usr/bin/env bash
# Builds the backend with PyInstaller and installs it where the Tauri app
# runs it from (app/src-tauri/binaries/ssb-backend/). Used by local dev and
# .github/workflows/release.yml alike.
#
# Builds from its own venv, backend/.venv-build, holding only the main deps
# plus the `build` group. PyInstaller bundles whatever's importable in the
# venv it runs from, and a venv that also had `convert` (optimum) installed
# once shipped torch inside the binary (implementation-plan.md Step 4). A
# separate venv keeps that guarantee without making the everyday .venv
# build-only: `uv sync --group X` removes every group not named, so one
# shared venv meant tests broke after each build and vice versa.
set -euo pipefail

cd "$(dirname "$0")/.."
export UV_PROJECT_ENVIRONMENT=.venv-build

uv sync --group build --frozen
uv run --no-sync pyinstaller ssb-backend.spec --distpath dist --workpath build --noconfirm

torch_modules=$(grep -c "^  ('torch\." build/ssb-backend/Analysis-00.toc || true)
if [[ "$torch_modules" != "0" ]]; then
  echo "error: torch got bundled ($torch_modules modules); .venv-build must only have the build group" >&2
  exit 1
fi

# cp -R keeps the onedir folder's symlinks as symlinks.
mkdir -p ../app/src-tauri/binaries
rm -rf ../app/src-tauri/binaries/ssb-backend
cp -R dist/ssb-backend ../app/src-tauri/binaries/ssb-backend
echo "installed: app/src-tauri/binaries/ssb-backend/"
