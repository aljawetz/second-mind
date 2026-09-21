"""Course sync orchestrator — docs/superpowers/specs/2026-09-20-course-sync-phase1-design.md.

Wires canvas.py + ingestion.py + indexing.py together via sync.py's
manifest-diff mechanism into a real, incremental sync pipeline. sync.py
itself stays Canvas-agnostic (its own docstring: "the caller ... is
responsible for the actual Canvas calls") — this module is that caller.
"""

import tempfile
from pathlib import Path

import httpx

import canvas
import ingestion
import indexing
import sync

SUPPORTED_FILE_SUFFIXES = {".pdf", ".pptx"}


def _course_paths(ssb_home: Path, course_id: int) -> tuple[Path, Path]:
    course_dir = ssb_home / "courses" / str(course_id)
    course_dir.mkdir(parents=True, exist_ok=True)
    return course_dir / "manifest.db", ssb_home / "index.lancedb"


def _sync_deleted(conn, db_path, table_name, item_type, deleted_ids):
    for prefixed_id in deleted_ids:
        indexing.delete_ref_doc_nodes(db_path, table_name, prefixed_id)
        sync.forget(conn, prefixed_id, item_type)
        yield {"item": prefixed_id, "status": "done"}


def _sync_file(conn, db_path, table_name, file_meta, is_changed):
    prefixed_id = f"file:{file_meta['id']}"
    display_name = file_meta.get("display_name", "")
    updated_at = file_meta.get("updated_at", "")
    suffix = Path(display_name).suffix.lower()

    if is_changed:
        indexing.delete_ref_doc_nodes(db_path, table_name, prefixed_id)

    raw = httpx.get(file_meta["url"], follow_redirects=True, timeout=60).content
    tmp_path = Path(tempfile.mktemp(suffix=suffix))
    tmp_path.write_bytes(raw)
    try:
        if suffix == ".pdf":
            pages = ingestion.extract_pdf(tmp_path)
            for p in pages:
                if p["needs_fallback"]:
                    p["text"] = ingestion.ocr_pdf_page(tmp_path, p["page"])
            nodes = indexing.pages_to_nodes(pages, display_name, prefixed_id)
            full_text = "".join(p["text"] for p in pages)
        else:  # .pptx
            slides = ingestion.extract_pptx(tmp_path)
            nodes = indexing.slides_to_nodes(slides, display_name, prefixed_id)
            full_text = "".join(s["text"] for s in slides)
    finally:
        tmp_path.unlink()

    if nodes:
        indexing.add_nodes(nodes, db_path, table_name)
    sync.mark_synced(conn, prefixed_id, "file", display_name, updated_at, sync.content_hash(full_text))
    return display_name


def _sync_page(conn, db_path, table_name, course_id, page_summary, is_changed):
    prefixed_id = f"page:{page_summary['url']}"
    updated_at = page_summary.get("updated_at", "")

    if is_changed:
        indexing.delete_ref_doc_nodes(db_path, table_name, prefixed_id)

    full = canvas.get_page(course_id, page_summary["url"])
    title = (full or {}).get("title") or page_summary.get("title") or page_summary["url"]
    text = ingestion.extract_html_page((full or {}).get("body") or "")
    # item_type="page": a Canvas wiki page is a flat document, not
    # paginated like a PDF — generation.py's citation formatting reads
    # item_type back as source_type, so this must say "page", not "file",
    # and carries no fabricated page number.
    nodes = indexing.pages_to_nodes(
        [{"page": None, "text": text, "needs_fallback": False}], title, prefixed_id, item_type="page"
    )

    if nodes:
        indexing.add_nodes(nodes, db_path, table_name)
    sync.mark_synced(conn, prefixed_id, "page", title, updated_at, sync.content_hash(text))
    return title


def sync_course(course_id: int, ssb_home: Path):
    """Generator — see module docstring and the design spec for the full
    contract. Yields {"item", "status", "error"?} per processed item, then
    exactly one final {"done": True, "new", "changed", "removed", "failed"}
    summary, or {"done": True, "error": str} (nothing else yielded first)
    if the course couldn't be synced at all."""
    manifest_path, db_path = _course_paths(ssb_home, course_id)
    table_name = f"course_{course_id}"
    conn = sync.open_manifest(manifest_path)

    try:
        structure = canvas.get_course_structure(course_id)
        pages_list = canvas.list_pages(course_id)
    except (canvas.CanvasError, httpx.HTTPStatusError, httpx.TransportError) as e:
        yield {"done": True, "error": str(e)}
        return

    file_items = [item for module in structure for item in module.get("items", []) if item.get("type") == "File"]

    new_count = changed_count = removed_count = failed_count = 0

    # Metadata collection itself can fail per-item (a malformed module item
    # missing content_id, or get_file hitting a real Canvas/network error) —
    # isolated here the same as the extraction/indexing failures below, so
    # one bad file doesn't abort the whole course sync.
    file_metas = {}
    for item in file_items:
        try:
            meta = canvas.get_file(item["content_id"])
        except Exception as e:
            failed_count += 1
            yield {"item": str(item.get("content_id", "?")), "status": "failed", "error": str(e)}
            continue
        if meta is None:
            continue
        display_name = meta.get("display_name", "")
        if Path(display_name).suffix.lower() not in SUPPORTED_FILE_SUFFIXES:
            print(f"[course_sync] skipping unsupported file: {display_name}")
            continue
        file_metas[str(meta["id"])] = meta

    file_remote = [{"id": f"file:{fid}", "updated_at": meta.get("updated_at", "")} for fid, meta in file_metas.items()]
    page_remote = [{"id": f"page:{p['url']}", "updated_at": p.get("updated_at", "")} for p in pages_list]
    pages_by_url = {p["url"]: p for p in pages_list}

    file_diff = sync.diff(conn, "file", file_remote)
    page_diff = sync.diff(conn, "page", page_remote)

    for event in _sync_deleted(conn, db_path, table_name, "file", file_diff["deleted"]):
        removed_count += 1
        yield event
    for event in _sync_deleted(conn, db_path, table_name, "page", page_diff["deleted"]):
        removed_count += 1
        yield event

    for ids, is_changed in ((file_diff["new"], False), (file_diff["changed"], True)):
        for prefixed_id in ids:
            fid = prefixed_id.removeprefix("file:")
            meta = file_metas[fid]
            try:
                name = _sync_file(conn, db_path, table_name, meta, is_changed)
                yield {"item": name, "status": "done"}
                changed_count += is_changed
                new_count += not is_changed
            except Exception as e:
                failed_count += 1
                yield {"item": meta.get("display_name", fid), "status": "failed", "error": str(e)}

    for ids, is_changed in ((page_diff["new"], False), (page_diff["changed"], True)):
        for prefixed_id in ids:
            url = prefixed_id.removeprefix("page:")
            page_summary = pages_by_url[url]
            try:
                title = _sync_page(conn, db_path, table_name, course_id, page_summary, is_changed)
                yield {"item": title, "status": "done"}
                changed_count += is_changed
                new_count += not is_changed
            except Exception as e:
                failed_count += 1
                yield {"item": page_summary.get("title", url), "status": "failed", "error": str(e)}

    yield {"done": True, "new": new_count, "changed": changed_count, "removed": removed_count, "failed": failed_count}
