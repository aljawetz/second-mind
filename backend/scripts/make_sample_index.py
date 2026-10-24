"""Build a tiny made-up course index for the search-only proof run.

The pages are invented (see SAMPLE_PAGES in ask_modes_eval.py). Nothing
here is from a real course. Needs the local embedding model
(scripts/convert_embedding_model.py). Run from backend/:

    uv run python3 scripts/make_sample_index.py --out /tmp/sample.lancedb
    uv run python3 scripts/ask_modes_eval.py --set sample --retrieval-only \\
        --index /tmp/sample.lancedb --out /tmp/sample.json
"""

import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

import ask_modes_eval
import indexing


def build_sample_index(db_path: Path) -> Path:
    """Write the sample course table and return db_path."""
    db_path = Path(db_path)
    if db_path.exists():
        shutil.rmtree(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    nodes = []
    for page in ask_modes_eval.SAMPLE_PAGES:
        nodes += indexing.pages_to_nodes(
            [{"page": page["page"], "text": page["text"]}],
            page["source"],
            page["item_id"],
        )
    indexing.build_index(nodes, db_path, f"course_{ask_modes_eval.SAMPLE_COURSE}")
    return db_path


def main():
    parser = argparse.ArgumentParser(description="Build the made-up sample course index.")
    parser.add_argument("--out", required=True, help="LanceDB directory to create")
    args = parser.parse_args()
    path = build_sample_index(Path(args.out))
    print(f"wrote sample course {ask_modes_eval.SAMPLE_COURSE} to {path}")


if __name__ == "__main__":
    main()
