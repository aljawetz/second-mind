"""End-to-end integration smoke test — chains everything built in Steps
1-7 together against real, live data for the first time. Every test up to
this point exercises one step in isolation (Step 3 replays cached Canvas
JSON, Step 5/6 use cached extraction fixtures, Step 7's diff test uses a
synthetic listing) — nothing has gone Canvas -> extract -> embed -> index
-> retrieve as one continuous, live chain until this script.

Not a pytest test: needs live Canvas access (a real token in Keychain)
and takes real time (embedding + OCR on real files). Run directly:

    uv run python3 scripts/integration_smoke_test.py

Needs models/bge-small-en-v1.5-onnx/ (scripts/convert_embedding_model.py).
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import httpx

import canvas
import ingestion
import indexing
import sync

COURSE_ID = 55710  # 18654-SV, Software Testing and Operations
FILE_LIMIT = 8

# 56350's "CatherineFang_Bio.pdf" (content_id 14690029) — a real named
# individual's personal biographical document, not course material. Found
# and excluded once already; kept as an explicit denylist entry rather
# than trusting "grab the first N files" not to pick it up again.
EXCLUDE_FILE_IDS = {14690029}


def log(msg: str):
    print(f"[smoke] {msg}")


def sync_file(conn, db_path: Path, file_id: int, table_name: str) -> dict | None:
    """Fetch, extract, chunk, embed, and index one real Canvas file, then
    record it in the manifest — the full Step 3->7 chain for one item."""
    meta = canvas.get_file(file_id)
    if meta is None:
        log(f"  file {file_id}: 403/404, skipping")
        return None

    canvas_item_id = str(file_id)
    name = meta.get("display_name", "")
    updated_at = meta.get("updated_at", "")
    log(f"  file {file_id} ({name}): fetching content")

    raw = httpx.get(meta["url"], follow_redirects=True, timeout=60).content
    bytes_hash = sync.raw_bytes_hash(raw)

    suffix = Path(name).suffix.lower()
    tmp_path = Path(tempfile.mktemp(suffix=suffix))
    tmp_path.write_bytes(raw)

    if suffix == ".pdf":
        pages = ingestion.extract_pdf(tmp_path)
        for p in pages:
            if p["needs_fallback"]:
                log(f"    page {p['page']}: density-flagged, running OCR")
                p["text"] = ingestion.ocr_pdf_page(tmp_path, p["page"])
        nodes = indexing.pages_to_nodes(pages, name, canvas_item_id)
        full_text = "".join(p["text"] for p in pages)
    elif suffix == ".pptx":
        slides = ingestion.extract_pptx(tmp_path)
        nodes = indexing.slides_to_nodes(slides, name, canvas_item_id)
        full_text = "".join(s["text"] for s in slides)
    else:
        log(f"    unsupported type {suffix}, skipping")
        tmp_path.unlink()
        return None

    tmp_path.unlink()

    if not nodes:
        log("    no extractable content, skipping index")
        return None

    content_hash = sync.content_hash(full_text)
    index = indexing.build_index(nodes, db_path, table_name)
    sync.mark_synced(conn, canvas_item_id, "file", updated_at, content_hash)
    log(f"    indexed {len(nodes)} nodes, bytes_hash={bytes_hash[:8]}, content_hash={content_hash[:8]}")
    return {"canvas_item_id": canvas_item_id, "name": name, "updated_at": updated_at}


def main():
    with tempfile.TemporaryDirectory() as scratch:
        scratch_path = Path(scratch)
        conn = sync.open_manifest(scratch_path / "manifest.db")
        db_path = scratch_path / "index.lancedb"
        table_name = f"course_{COURSE_ID}"

        log(f"listing real module items for course {COURSE_ID} (live Canvas call)")
        structure = canvas.get_course_structure(COURSE_ID)
        file_items = [
            item
            for module in structure
            for item in module.get("items", [])
            if item.get("type") == "File" and item.get("content_id") not in EXCLUDE_FILE_IDS
        ][:FILE_LIMIT]
        if not file_items:
            log("no file items found in this course — nothing to test")
            sys.exit(1)

        remote_listing = []
        for item in file_items:
            file_id = item["content_id"]
            meta = canvas.get_file(file_id)
            if meta:
                remote_listing.append({"id": str(file_id), "updated_at": meta.get("updated_at", "")})

        log(f"diffing against a fresh manifest — {len(remote_listing)} real items")
        result = sync.diff(conn, "file", remote_listing)
        assert result["new"] == [r["id"] for r in remote_listing], "expected every item to be 'new' on first sync"
        log(f"  bucket: {result}")

        log("running the full sync chain for each new item")
        synced = []
        for item in file_items:
            row = sync_file(conn, db_path, item["content_id"], table_name)
            if row:
                synced.append(row)

        if not synced:
            log("nothing successfully indexed — cannot test retrieval")
            sys.exit(1)

        log("re-diffing against the SAME live Canvas listing — expect all 'unchanged'")
        result2 = sync.diff(conn, "file", remote_listing)
        log(f"  bucket: {result2}")
        assert result2["new"] == [] and result2["changed"] == [], (
            f"expected no new/changed items on a re-sync with no remote changes, got {result2}"
        )
        log("  confirmed: real Canvas updated_at timestamps round-trip correctly through the manifest")

        log("running a real retrieval query against the freshly-built index")
        index = indexing.build_index([], db_path, table_name)  # reopen the existing table
        retriever = index.as_retriever(similarity_top_k=3)
        query = "What is a test double and how does Mockito help isolate components?"
        results = retriever.retrieve(query)
        for r in results:
            log(f"  hit: source={r.metadata.get('source')!r} score={r.score:.3f} text={r.text[:80]!r}")
        assert len(results) > 0, "expected at least one retrieval result"

        log("ALL CHECKS PASSED — the full Canvas -> extract -> embed -> index -> sync -> retrieve chain works end-to-end on real data")


if __name__ == "__main__":
    main()
