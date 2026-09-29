#!/usr/bin/env bash
# Thin wrapper: the build lives in build_sidecar.py so macOS and Windows share it.
set -euo pipefail

cd "$(dirname "$0")/.."
exec uv run --no-project python scripts/build_sidecar.py
