"""One-time setup: fetch the faster-whisper "base" CTranslate2 model for
local, offline session transcription.

Run once per dev/CI machine: `uv run python3 scripts/fetch_whisper_model.py`

Bundled into the shipped binary the same way as the BGE embedding model
(implementation-plan.md Step 4) rather than left to download from Hugging
Face on first real use — a recording feature needing network access the
first time a student uses it, possibly mid-class on spotty wifi, would
undercut this app's whole "your machine, your index" local-first design
(design spec §5.1).

Output isn't committed to git: model.bin alone is ~145MB, over GitHub's
100MB per-file push limit, and it's deterministically regenerable from a
stable public checkpoint — same reasoning as the ONNX embedding model.
"""

from pathlib import Path

from huggingface_hub import snapshot_download

MODEL_ID = "Systran/faster-whisper-base"
OUTPUT_DIR = Path(__file__).parent.parent / "models" / "faster-whisper-base"

if __name__ == "__main__":
    OUTPUT_DIR.parent.mkdir(exist_ok=True)
    snapshot_download(MODEL_ID, local_dir=OUTPUT_DIR)
    print(f"fetched to {OUTPUT_DIR}")
