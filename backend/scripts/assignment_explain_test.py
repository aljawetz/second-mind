"""Assignment explainer boundary test — implementation-plan.md Step 10,
design spec §7.1. Scripted, not manual: re-runs the real boundary check
against the same real assignment (course 55710's "A1 - Test Doubles",
id 1008907 — a real coding assignment with concrete class/method names,
the exact shape the design spec's manual test found risky) and asserts
build_pointers never names any of them.

Not a pytest test: makes real, billed OpenAI API calls and needs live
Canvas access. Run directly:

    uv run python3 scripts/assignment_explain_test.py

Needs a real OpenAI key in Keychain (Step 2) and
models/bge-small-en-v1.5-onnx/ (scripts/convert_embedding_model.py).
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import httpx

import canvas
import explain
import ingestion
import indexing

COURSE_ID = 55710  # 18654-SV, Software Testing and Operations
ASSIGNMENT_ID = 1008907  # A1 - Test Doubles
FILE_LIMIT = 8
EXCLUDE_FILE_IDS = {14690029}  # see integration_smoke_test.py


def log(msg: str):
    print(f"[explain-test] {msg}")


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
    assignment = canvas.get_assignment(COURSE_ID, ASSIGNMENT_ID)
    assert assignment, f"assignment {ASSIGNMENT_ID} not found — has it moved or been removed?"
    name = assignment["name"]
    raw_html = assignment.get("description") or ""
    description_text = explain.html_to_text(raw_html)
    log(f"assignment: {name!r} ({len(description_text)} chars of plain text)")

    identifiers = explain.extract_code_identifiers(raw_html)
    log(f"real code identifiers named in the prompt: {sorted(identifiers)}")
    assert identifiers, "expected this real assignment to name at least one <code> identifier"

    log("building breakdown (reading comprehension only, no course retrieval)")
    breakdown = explain.build_breakdown(name, description_text)
    assert breakdown, "expected at least one sub-requirement"
    log(f"  {len(breakdown)} sub-requirements:")
    for item in breakdown:
        log(f"    - {item}")

    with tempfile.TemporaryDirectory() as scratch:
        db_path = Path(scratch) / "index.lancedb"
        index = build_real_index(db_path, f"course_{COURSE_ID}")

        log("building pointers (retrieval only, no LLM-authored guidance text)")
        pointers = explain.build_pointers(index, name, description_text)
        log(f"  {len(pointers)} pointers:")
        for p in pointers:
            log(f"    - {p['label']} (item_id={p['item_id']})")

        log("boundary check: no pointer label may name a real code identifier from the prompt")
        for p in pointers:
            for ident in identifiers:
                assert ident not in p["label"], (
                    f"pointer {p!r} names {ident!r} — implementation guidance leaking into a pointer"
                )

    log("ALL CHECKS PASSED")


if __name__ == "__main__":
    main()
