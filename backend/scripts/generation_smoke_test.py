"""Generation smoke test — implementation-plan.md Step 8. Verifies real
citations, the not-covered case, and Socratic mode against a real index
with a real LLM call.

Not a pytest test: makes real, billed OpenAI API calls and needs live
Canvas access. Run directly:

    uv run python3 scripts/generation_smoke_test.py

Needs a real OpenAI key in Keychain (Step 2) and
models/bge-small-en-v1.5-onnx/ (scripts/convert_embedding_model.py).
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import httpx

import canvas
import ingestion
import indexing
import generation

COURSE_ID = 55710  # 18654-SV, Software Testing and Operations
FILE_LIMIT = 8
EXCLUDE_FILE_IDS = {14690029}  # see integration_smoke_test.py


def log(msg: str):
    print(f"[gen-smoke] {msg}")


def build_real_index(db_path: Path, table_name: str):
    structure = canvas.get_course_structure(COURSE_ID)
    file_items = [
        item
        for module in structure
        for item in module.get("items", [])
        if item.get("type") == "File" and item.get("content_id") not in EXCLUDE_FILE_IDS
    ][:FILE_LIMIT]

    nodes = []
    for item in file_items:
        meta = canvas.get_file(item["content_id"])
        if not meta:
            continue
        name = meta.get("display_name", "")
        raw = httpx.get(meta["url"], follow_redirects=True, timeout=60).content
        suffix = Path(name).suffix.lower()
        tmp_path = Path(tempfile.mktemp(suffix=suffix))
        tmp_path.write_bytes(raw)
        if suffix == ".pdf":
            pages = ingestion.extract_pdf(tmp_path)
            for p in pages:
                if p["needs_fallback"]:
                    p["text"] = ingestion.ocr_pdf_page(tmp_path, p["page"])
            nodes += indexing.pages_to_nodes(pages, name, str(item["content_id"]))
        tmp_path.unlink()

    log(f"indexed {len(nodes)} nodes from {len(file_items)} files")
    return indexing.build_index(nodes, db_path, table_name)


def main():
    with tempfile.TemporaryDirectory() as scratch:
        db_path = Path(scratch) / "index.lancedb"
        index = build_real_index(db_path, f"course_{COURSE_ID}")

        log("on-topic query (answer-first)")
        engine = generation.build_query_engine(index, socratic=False, streaming=False)
        r = engine.query("What is a test double and how does Mockito help isolate components?")
        assert r.source_nodes, "expected citations for an on-topic query"
        assert all(n.score >= generation.SIMILARITY_CUTOFF for n in r.source_nodes)
        log(f"  answer: {r.response[:100]!r}")
        log(f"  cited {len(r.source_nodes)} nodes, all >= cutoff")

        log("off-topic query (expect no citations, no hallucination)")
        r2 = engine.query("What is the recipe for a chocolate souffle?")
        assert not r2.source_nodes, f"expected zero source nodes for an off-topic query, got {len(r2.source_nodes)}"
        log(f"  response: {r2.response!r}, source_nodes={len(r2.source_nodes)}")

        log("Socratic mode (expect a guiding question, not a direct answer)")
        socratic_engine = generation.build_query_engine(index, socratic=True, streaming=False)
        r3 = socratic_engine.query("What is spec-based testing?")
        assert "?" in r3.response, "expected Socratic mode to ask a guiding question"
        log(f"  answer: {r3.response[:150]!r}")

        log("ALL CHECKS PASSED")


if __name__ == "__main__":
    main()
