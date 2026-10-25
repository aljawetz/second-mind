"""One-time setup: convert bge-reranker-base to ONNX for local reranking.

Run once per dev machine (or after bumping MODEL_ID):
`uv run --all-groups python3 scripts/convert_reranker_model.py` from backend/.
Same approach as convert_embedding_model.py: optimum[onnx] (dev group only)
pulls torch for the export, but the app only needs onnxruntime at runtime.

Output is not committed: model.onnx is about 1.1GB. Without it, search
still works and just skips the rerank step (see reranker.load_reranker).
"""

import subprocess
import sys
from pathlib import Path

MODEL_ID = "BAAI/bge-reranker-base"
OUTPUT_DIR = Path(__file__).parent.parent / "models" / "bge-reranker-base-onnx"

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
