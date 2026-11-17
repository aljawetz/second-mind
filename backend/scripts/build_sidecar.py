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
import subprocess
import sys
from pathlib import Path

backend = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend))
from build_support import install_sidecar
env = {**os.environ, "UV_PROJECT_ENVIRONMENT": ".venv-build"}

if sys.platform == "win32":
    from native_tools import tesseract_executable

    tesseract = tesseract_executable()
    if not tesseract:
        sys.exit("Install Tesseract OCR before building: winget install UB-Mannheim.TesseractOCR")
    if not (tesseract.parent / "tessdata" / "eng.traineddata").is_file():
        sys.exit(f"English OCR data missing beside {tesseract}")
    env["SM_TESSERACT_DIR"] = str(tesseract.parent)


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

# symlinks=True keeps the onedir folder's symlinks as symlinks (macOS).
dest = (backend.parent / "app" / "src-tauri" / "binaries" / "sm-backend").resolve()
assert dest.is_relative_to(backend.parent.resolve())
dest.parent.mkdir(parents=True, exist_ok=True)
install_sidecar(backend / "dist" / "sm-backend", dest, backend.parent)
print("installed: app/src-tauri/binaries/sm-backend/")
