#!/usr/bin/env python3
"""One-shot dev environment setup: collapses backend/README.md's multi-step
setup (uv sync, model conversion, model fetch, npm install) into a single
command, contribution-and-distribution-plan.md step 3.

Runs on macOS and Windows: `python scripts/bootstrap.py`. Linux is untested.
"""

import shutil
import subprocess
import sys
from pathlib import Path

repo_root = Path(__file__).resolve().parent.parent
backend = repo_root / "backend"
app = repo_root / "app"
is_windows = sys.platform == "win32"


def find_cargo() -> str | None:
    return shutil.which("cargo") or shutil.which(
        "cargo", path=str(Path.home() / ".cargo" / "bin")
    )


def check_prerequisites() -> None:
    if is_windows:
        tesseract_hint = "tesseract (https://github.com/UB-Mannheim/tesseract/wiki, add it to PATH)"
        node_hint = "node (https://nodejs.org)"
    else:
        tesseract_hint = "tesseract (brew install tesseract)"
        node_hint = "node (https://nodejs.org, or: brew install node)"
    missing = []
    if not shutil.which("uv"):
        missing.append("uv (https://docs.astral.sh/uv/getting-started/installation/)")
    if not shutil.which("node"):
        missing.append(node_hint)
    if not shutil.which("npm"):
        missing.append("npm (comes with node)")
    if not shutil.which("tesseract"):
        missing.append(tesseract_hint)
    if not find_cargo():
        missing.append("rust (https://rustup.rs)")
    if missing:
        print("Missing prerequisites:", file=sys.stderr)
        for m in missing:
            print(f"  - {m}", file=sys.stderr)
        sys.exit(1)


def step(title: str, cwd: Path, *cmd: str) -> None:
    print(f"==> {title}", flush=True)
    # shutil.which resolves npm.cmd on Windows, which CreateProcess won't find by bare name.
    resolved = shutil.which(cmd[0]) or cmd[0]
    subprocess.run([resolved, *cmd[1:]], cwd=cwd, check=True)


check_prerequisites()

step("Backend: installing Python dependencies (uv sync --all-groups)",
     backend, "uv", "sync", "--all-groups")
step("Backend: generating the local embedding model (one-time, needs network access to Hugging Face)",
     backend, "uv", "run", "python", "scripts/convert_embedding_model.py")
step("Backend: fetching the session-transcription model (one-time, needs network access to Hugging Face)",
     backend, "uv", "run", "python", "scripts/fetch_whisper_model.py")
step("Backend: running the test suite to confirm the environment is sound",
     backend, "uv", "run", "pytest", "tests/", "-q")
# After the model steps: the spec bundles both models into the build.
step("Backend: building it for the app (PyInstaller, in its own .venv-build)",
     backend, "uv", "run", "--no-project", "python", "scripts/build_sidecar.py")
step("Frontend: installing npm dependencies", app, "npm", "install")

if is_windows:
    start = "    cd app\n    npm run tauri dev"
    note = "Rerun backend\\scripts\\build_sidecar.py after changing backend code you want to see in the app."
else:
    start = '    cd app\n    PATH="$HOME/.cargo/bin:$PATH" npm run tauri dev'
    note = (
        "The first launch after a fresh backend build takes ~35s while macOS scans\n"
        "the new files; later launches start in ~2s. Rerun backend/scripts/build_sidecar.sh\n"
        "after changing backend code you want to see in the app."
    )
print(f"\n==> Done. Start the app with:\n\n{start}\n\n{note}")
