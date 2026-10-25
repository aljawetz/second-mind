"""One-time setup: convert ms-marco-MiniLM-L-6-v2 to ONNX for local reranking.

Run once per dev machine (or after bumping MODEL_ID):
`uv run --all-groups python3 scripts/convert_reranker_model.py` from backend/.
Same approach as convert_embedding_model.py: optimum[onnx] (dev group only)
pulls torch for the export, but the app only needs onnxruntime at runtime.
Sprint 8 tried BAAI/bge-reranker-base first: similar quality on the
sprint7 eval, but 1.1GB and about 4x slower (see PR #23).

Output is not committed: model.onnx is about 88MB, and it regenerates from a public checkpoint. Without it, search
still works and just skips the rerank step (see reranker.load_reranker).
"""

import subprocess
import sys
from pathlib import Path

MODEL_ID = "cross-encoder/ms-marco-MiniLM-L-6-v2"
OUTPUT_DIR = Path(__file__).parent.parent / "models" / "ms-marco-MiniLM-L-6-v2-onnx"

if __name__ == "__main__":
    OUTPUT_DIR.parent.mkdir(exist_ok=True)
    result = subprocess.run(
        [
            "optimum-cli", "export", "onnx",
            "--model", MODEL_ID,
            "--task", "text-classification",
            str(OUTPUT_DIR),
        ]
    )
    sys.exit(result.returncode)
