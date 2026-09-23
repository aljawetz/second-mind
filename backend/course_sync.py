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

    # Pages found via Modules or the front page were already fetched in full
    # (body included) to learn their updated_at; only list_pages summaries,
    # which never carry a body, need fetching here.
    full = page_summary if "body" in page_summary else canvas.get_page(course_id, page_summary["url"])
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


def _sync_syllabus(conn, db_path, table_name, course_id, syllabus_html, version, is_changed):
    prefixed_id = f"syllabus:{course_id}"
    if is_changed:
        indexing.delete_ref_doc_nodes(db_path, table_name, prefixed_id)

    text = ingestion.extract_html_page(syllabus_html)
    # Own item_type so citations.ts can open Canvas's syllabus URL
    # (/assignments/syllabus), which isn't under /pages/.
    nodes = indexing.pages_to_nodes(
        [{"page": None, "text": text, "needs_fallback": False}], "Syllabus", prefixed_id, item_type="syllabus"
    )
    if nodes:
        indexing.add_nodes(nodes, db_path, table_name)
    sync.mark_synced(conn, prefixed_id, "syllabus", "Syllabus", version, sync.content_hash(text))
    return "Syllabus"


def _deletable(remote_items: list[dict], deleted_ids: list[str], unresolved_ids: set[str]) -> list[str]:
    """Which of diff()'s "deleted" ids are safe to actually destroy.

    canvas.py's HTTP layer degrades a 403/404 to None / an empty list
    (its own docstring: "not available to this token"), which is
    indistinguishable from "this course genuinely has zero items" or
    "this item is genuinely gone". Absence from a listing is therefore
    *not* trustworthy evidence of deletion, and acting on it can silently
    destroy a course's whole indexed corpus — expensive to rebuild, and
    with no manual re-sync UI in this phase, unrecoverable until a much
    later one. So two guards:

      - an entirely empty remote listing deletes nothing (highest-risk,
        least distinguishable case — a hidden/locked modules tab looks
        exactly like an empty course);
      - an item whose own metadata fetch failed or 403'd this round is
        excluded, so a transient per-item failure can't both report
        "failed" and wipe that item's real index entry in the same run.

    The tradeoff is deliberate: stale manifest/index rows linger until a
    listing succeeds again, which is strictly better than destroying
    real content on ambiguous evidence.
    """
    if not remote_items:
        return []
    return [i for i in deleted_ids if i not in unresolved_ids]


def sync_course(course_id: int, ssb_home: Path):
    """Generator — see module docstring and the design spec for the full
    contract. Yields {"item", "status", "error"?} per processed item, then
    exactly one final {"done": True, "new", "changed", "removed", "failed"}
    summary, or {"done": True, "error": str} if the course couldn't be
    synced at all. Exactly one terminal ("done") event always fires, even
    if something unexpected blows up mid-stream — main.py has already sent
    the 200 and streaming headers by the time this generator's body runs,
    so an uncaught exception here would leave the connection dying
    mid-stream with no terminating event for the frontend to act on."""
    manifest_path, db_path = _course_paths(ssb_home, course_id)
    table_name = f"course_{course_id}"
    conn = sync.open_manifest(manifest_path)

    try:
        structure = canvas.get_course_structure(course_id)
        pages_list = canvas.list_pages(course_id)
        front_page = canvas.get_front_page(course_id)
        syllabus_html = canvas.get_syllabus(course_id)
    except (canvas.CanvasError, httpx.HTTPStatusError, httpx.TransportError) as e:
        yield {"done": True, "error": str(e)}
        return

    file_items = [item for module in structure for item in module.get("items", []) if item.get("type") == "File"]

    new_count = changed_count = removed_count = failed_count = 0

    # Coarse safety net over the fine-grained per-item try/excepts below
    # (which still isolate one file/page's failure from the rest). Its only
    # job is the "exactly one terminal event, always" guarantee above —
    # sync.diff() and _sync_deleted()'s index/manifest writes are otherwise
    # unguarded, and an exception from either would escape uncaught.
    try:
        # Metadata collection itself can fail per-item (a malformed module item
        # missing content_id, or get_file hitting a real Canvas/network error) —
        # isolated here the same as the extraction/indexing failures below, so
        # one bad file doesn't abort the whole course sync.
        file_metas = {}
        unresolved_file_ids: set[str] = set()
        for item in file_items:
            content_id = item.get("content_id")
            prefixed_id = f"file:{content_id}" if content_id is not None else None
            try:
                meta = canvas.get_file(item["content_id"])
            except Exception as e:
                failed_count += 1
                if prefixed_id:
                    unresolved_file_ids.add(prefixed_id)
                yield {"item": str(content_id) if content_id is not None else "?", "status": "failed", "error": str(e)}
                continue
            if meta is None:
                # get_file degraded a 403/404 to None — skip indexing it as
                # before, but record it as unresolved so its absence from
                # file_remote isn't mistaken for "deleted from Canvas".
                if prefixed_id:
                    unresolved_file_ids.add(prefixed_id)
                continue
            display_name = meta.get("display_name", "")
            if Path(display_name).suffix.lower() not in SUPPORTED_FILE_SUFFIXES:
                print(f"[course_sync] skipping unsupported file: {display_name}")
                continue
            file_metas[str(meta["id"])] = meta

        file_remote = [
            {"id": f"file:{fid}", "updated_at": meta.get("updated_at", "")} for fid, meta in file_metas.items()
        ]
        # Pages come from three places, merged by url slug. list_pages is
        # the Pages-tab listing, which 404s for students in most courses
        # (8 of 10 surveyed) — yet every Page item in those courses' Modules
        # opened fine individually (211 of 211), and five courses had no
        # other content at all. Module items carry no updated_at, so each
        # one is fetched in full here; the body is kept for _sync_page. A
        # fetch that fails or 404s is unresolved, not deleted — same guard
        # as files above.
        pages_by_url = {p["url"]: p for p in pages_list}
        if front_page and front_page.get("url"):
            pages_by_url.setdefault(front_page["url"], front_page)
        unresolved_page_ids: set[str] = set()
        module_page_urls = [
            item["page_url"] for module in structure for item in module.get("items", [])
            if item.get("type") == "Page" and item.get("page_url")
        ]
        for url in dict.fromkeys(module_page_urls):
            if url in pages_by_url:
                continue
            try:
                full = canvas.get_page(course_id, url)
            except Exception as e:
                failed_count += 1
                unresolved_page_ids.add(f"page:{url}")
                yield {"item": url, "status": "failed", "error": str(e)}
                continue
            if full is None:
                unresolved_page_ids.add(f"page:{url}")
                continue
            pages_by_url[url] = full
        page_remote = [{"id": f"page:{url}", "updated_at": p.get("updated_at", "")} for url, p in pages_by_url.items()]

        # The syllabus has no updated_at of its own: its content hash stands
        # in as the version, so an edit reads as "changed".
        syllabus_remote = []
        if syllabus_html and ingestion.extract_html_page(syllabus_html).strip():
            syllabus_remote = [{"id": f"syllabus:{course_id}", "updated_at": sync.content_hash(syllabus_html)}]

        file_diff = sync.diff(conn, "file", file_remote)
        page_diff = sync.diff(conn, "page", page_remote)
        syllabus_diff = sync.diff(conn, "syllabus", syllabus_remote)

        file_deleted = _deletable(file_remote, file_diff["deleted"], unresolved_file_ids)
        page_deleted = _deletable(page_remote, page_diff["deleted"], unresolved_page_ids)
        # Like the other empty-listing guards: a syllabus that comes back
        # empty or 403 is never taken as "removed".
        syllabus_deleted = _deletable(syllabus_remote, syllabus_diff["deleted"], set())

        for event in _sync_deleted(conn, db_path, table_name, "file", file_deleted):
            removed_count += 1
            yield event
        for event in _sync_deleted(conn, db_path, table_name, "page", page_deleted):
            removed_count += 1
            yield event
        for event in _sync_deleted(conn, db_path, table_name, "syllabus", syllabus_deleted):
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

        for ids, is_changed in ((syllabus_diff["new"], False), (syllabus_diff["changed"], True)):
            for _ in ids:
                try:
                    name = _sync_syllabus(
                        conn, db_path, table_name, course_id, syllabus_html, syllabus_remote[0]["updated_at"], is_changed
                    )
                    yield {"item": name, "status": "done"}
                    changed_count += is_changed
                    new_count += not is_changed
                except Exception as e:
                    failed_count += 1
                    yield {"item": "Syllabus", "status": "failed", "error": str(e)}
    except Exception as e:
        yield {"done": True, "error": str(e)}
        return

    yield {"done": True, "new": new_count, "changed": changed_count, "removed": removed_count, "failed": failed_count}
