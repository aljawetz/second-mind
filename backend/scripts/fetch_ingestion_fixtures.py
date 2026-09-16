"""One-time setup: fetch the real files Step 5's extraction tests run
against. Not committed — these are an instructor's actual course materials,
not ours to redistribute in a public repo (unlike the Canvas API JSON
fixtures in tests/fixtures/canvas/, which are our own structural data).

Needs a Canvas token in Keychain (implementation-plan.md Step 2) with
access to course 56350. Run once: `uv run python3 scripts/fetch_ingestion_fixtures.py`

The two named "sprint3_*" files are the exact ones Sprint 3 measured —
confirmed by re-extracting and comparing character counts, not assumed
from the file names alone (rag-pipeline.md §1, implementation-plan.md
Step 5). The measured baseline itself (character counts, not the files)
lives in tests/fixtures/ingestion_baseline.json, which *is* committed.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import httpx

import canvas

OUTPUT_DIR = Path(__file__).parent.parent / "tests" / "fixtures" / "ingestion"

FILES = {
    14690032: "sprint3_zotero_tutorial.pdf",
    14690037: "sprint3_ai_research.pptx",
    14690036: "research_study.pdf",
    14690035: "literature_review.pdf",
}

if __name__ == "__main__":
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for file_id, name in FILES.items():
        meta = canvas.get_file(file_id)
        if meta is None:
            print(f"could not fetch metadata for file {file_id} ({name}) — skipping", file=sys.stderr)
            continue
        r = httpx.get(meta["url"], follow_redirects=True, timeout=60)
        r.raise_for_status()
        path = OUTPUT_DIR / name
        path.write_bytes(r.content)
        print(f"saved {path} ({len(r.content)} bytes)")
