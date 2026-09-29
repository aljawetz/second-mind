#!/usr/bin/env bash
# Thin wrapper: the setup lives in bootstrap.py so macOS and Windows share it.
set -euo pipefail

exec python3 "$(dirname "${BASH_SOURCE[0]}")/bootstrap.py"
