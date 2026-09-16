"""One-time setup: convert bge-small-en-v1.5 to ONNX for local embeddings.

Run once per dev/CI machine (or after bumping MODEL_ID): `uv run backend/scripts/convert_embedding_model.py`
Needs the `dev` dependency group (`uv sync`) — torch is pulled in transiently
by `optimum[onnx]` to perform the export, but only here, never at runtime.
See docs/architecture/rag-pipeline.md §3 for why this exists (avoids
bundling torch into the shipped PyInstaller binary — a confirmed packaging
problem) and implementation-plan.md Step 4 for what was verified.

Output isn't committed to git: model.onnx alone is ~127MB, over GitHub's
100MB per-file push limit, and it's deterministically regenerable from a
stable public checkpoint — same reasoning as the gitignored sidecar binary.
"""

import subprocess
import sys
from pathlib import Path

MODEL_ID = "BAAI/bge-small-en-v1.5"
OUTPUT_DIR = Path(__file__).parent.parent / "models" / "bge-small-en-v1.5-onnx"

if __name__ == "__main__":
    OUTPUT_DIR.parent.mkdir(exist_ok=True)
    result = subprocess.run(
        [
            "optimum-cli", "export", "onnx",
            "--model", MODEL_ID,
            "--task", "feature-extraction",
            str(OUTPUT_DIR),
        ]
    )
    sys.exit(result.returncode)
