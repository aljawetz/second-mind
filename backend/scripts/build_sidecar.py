#!/usr/bin/env python3
"""Builds the backend with PyInstaller and installs it where the Tauri app
runs it from (app/src-tauri/binaries/sm-backend/). Used by local dev and
.github/workflows/release.yml alike. Runs on macOS and Windows.

Builds from its own venv, backend/.venv-build, holding only the main deps
plus the `build` group. PyInstaller bundles whatever's importable in the
venv it runs from, and a venv that also had `convert` (optimum) installed
once shipped torch inside the binary (implementation-plan.md Step 4). A
separate venv keeps that guarantee without making the everyday .venv
build-only: `uv sync --group X` removes every group not named, so one
shared venv meant tests broke after each build and vice versa.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

backend = Path(__file__).resolve().parent.parent
env = {**os.environ, "UV_PROJECT_ENVIRONMENT": ".venv-build"}


def run(*cmd: str) -> None:
    subprocess.run(cmd, cwd=backend, env=env, check=True)


run("uv", "sync", "--group", "build", "--frozen")
run(
    "uv", "run", "--no-sync", "pyinstaller", "sm-backend.spec",
    "--distpath", "dist", "--workpath", "build", "--noconfirm",
)

toc = backend / "build" / "sm-backend" / "Analysis-00.toc"
torch_modules = sum(
    1 for line in toc.read_text(encoding="utf-8").splitlines() if line.startswith("  ('torch.")
)
if torch_modules:
    sys.exit(
        f"error: torch got bundled ({torch_modules} modules); "
        ".venv-build must only have the build group"
    )

# Keep onedir symlinks on macOS, but dereference them on Windows so model
# directories are copied into the Tauri bundle rather than left unusable.
dest = backend.parent / "app" / "src-tauri" / "binaries" / "sm-backend"
dest.parent.mkdir(parents=True, exist_ok=True)
shutil.rmtree(dest, ignore_errors=True)
shutil.copytree(backend / "dist" / "sm-backend", dest, symlinks=os.name != "nt")
print("installed: app/src-tauri/binaries/sm-backend/")
