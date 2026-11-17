"""Course sync orchestrator — docs/superpowers/specs/2026-09-20-course-sync-phase1-design.md.

Wires canvas.py + ingestion.py + indexing.py together via sync.py's
manifest-diff mechanism into a real, incremental sync pipeline. sync.py
itself stays Canvas-agnostic (its own docstring: "the caller ... is
responsible for the actual Canvas calls") — this module is that caller.
"""

import re
import tempfile
import threading
from datetime import datetime, tzinfo
from pathlib import Path

import httpx

import canvas
import course_items
import ingestion
import indexing
import large_files
import sync

# File types read as sections (headings and their text), like Canvas pages.
SECTION_EXTRACTORS = {
    ".docx": "extract_docx",
    ".xlsx": "extract_xlsx",
    ".txt": "extract_text_file",
    ".md": "extract_text_file",
    ".csv": "extract_text_file",
}
SUPPORTED_FILE_SUFFIXES = {".pdf", ".pptx", *SECTION_EXTRACTORS}
_course_locks: dict[int, threading.Lock] = {}
_course_locks_guard = threading.Lock()


def _course_lock(sm_home: Path, course_id: int):
    del sm_home
    with _course_locks_guard:
        return _course_locks.setdefault(course_id, threading.Lock())


def _course_paths(sm_home: Path, course_id: int) -> tuple[Path, Path]:
    course_dir = sm_home / "courses" / str(course_id)
    course_dir.mkdir(parents=True, exist_ok=True)
    return course_dir / "manifest.db", sm_home / "index.lancedb"


def _sync_deleted(conn, db_path, table_name, item_type, deleted_ids):
    for prefixed_id in deleted_ids:
        indexing.delete_ref_doc_nodes(db_path, table_name, prefixed_id)
        sync.forget(conn, prefixed_id, item_type)
        if item_type == "file":
            large_files.forget(conn, prefixed_id.removeprefix("file:"))
        yield {"item": prefixed_id, "status": "done"}


def _cut_to(items: list[dict], limit: int, text_of) -> list[dict]:
    """The leading items whose text fits in `limit` characters (at least one)."""
    kept, total = [], 0
    for item in items:
        total += len(text_of(item))
        if kept and total > limit:
            break
        kept.append(item)
    return kept


def _sync_file(conn, db_path, table_name, file_meta, is_changed, version_suffix=""):
    """Indexes a file, or the preview large_files.py allows: version_suffix
    is "" (the whole file, unless it turns out long), "|preview" or
    "|skipped" (over the size limit: not downloaded)."""
    file_id = str(file_meta["id"])
    prefixed_id = f"file:{file_id}"
    display_name = file_meta.get("display_name", "")
    updated_at = file_meta.get("updated_at", "")
    size = file_meta.get("size") or 0
    suffix = Path(display_name).suffix.lower()
    want_full = large_files.wants_full(conn, file_id)

    if is_changed:
        indexing.delete_ref_doc_nodes(db_path, table_name, prefixed_id)

    if version_suffix == "|skipped":
        large_files.record(conn, file_id, display_name, size, pages=None, chars=None, long=False, state="none")
        sync.mark_synced(conn, prefixed_id, "file", display_name, updated_at + version_suffix, sync.content_hash(""))
        return display_name

    raw = canvas.download(file_meta["url"])
    tmp_path = Path(tempfile.mktemp(suffix=suffix))
    tmp_path.write_bytes(raw)
    pages_total = chars = None
    try:
        if suffix == ".pdf":
            pages_total = ingestion.pdf_page_count(tmp_path)
            long = pages_total > large_files.MAX_PDF_PAGES
            preview = long and not want_full
            pages = ingestion.extract_pdf(tmp_path, max_pages=large_files.MAX_PDF_PAGES) if preview else ingestion.extract_pdf(tmp_path)
            for p in pages:
                if p["needs_fallback"]:
                    p["text"] = ingestion.merge_ocr_text(p["text"], ingestion.ocr_pdf_page(tmp_path, p["page"]))
            source = large_files.preview_source(display_name, pages_total) if preview else display_name
            nodes = indexing.pages_to_nodes(pages, source, prefixed_id)
            full_text = "".join(p["text"] for p in pages)
        elif suffix == ".pptx":
            slides = ingestion.extract_pptx(tmp_path)
            chars = sum(len(s["text"]) for s in slides)
            long = chars > large_files.MAX_TEXT_CHARS
            preview = long and not want_full
            if preview:
                slides = _cut_to(slides, large_files.MAX_TEXT_CHARS, lambda s: s["text"])
            source = large_files.preview_source(display_name, None) if preview else display_name
            nodes = indexing.slides_to_nodes(slides, source, prefixed_id)
            full_text = "".join(s["text"] for s in slides)
        else:  # Word, Excel, plain text
            sections = getattr(ingestion, SECTION_EXTRACTORS[suffix])(tmp_path)
            chars = len(ingestion.sections_text(sections))
            long = chars > large_files.MAX_TEXT_CHARS
            preview = long and not want_full
            if preview:
                sections = _cut_to(sections, large_files.MAX_TEXT_CHARS, lambda s: f"{s['heading'] or ''}{s['text'] or ''}")
            source = large_files.preview_source(display_name, None) if preview else display_name
            nodes = indexing.sections_to_nodes(sections, source, prefixed_id, "file")
            full_text = ingestion.sections_text(sections)
    finally:
        tmp_path.unlink()

    if nodes:
        indexing.add_nodes(nodes, db_path, table_name)
    if long or size > large_files.MAX_FILE_BYTES or want_full:
        state = "preview" if preview else "full"
        large_files.record(conn, file_id, display_name, size, pages=pages_total, chars=chars, long=long, state=state)
    else:
        large_files.forget(conn, file_id)
    version = updated_at + ("|preview" if preview else "")
    sync.mark_synced(conn, prefixed_id, "file", display_name, version, sync.content_hash(full_text))
    return display_name


# The course's Home, when it's a wiki page: indexed as "Home: <title>" so
# "what's on the Home page?" finds it. 18-658's Home is titled "Welcome to
# Software Requirements and Interaction Design (18-658)!", and under that
# title alone the question found nothing (seen in the app, 2026-11-17). The
# version suffix makes a front page synced before this resync once.
HOME_SUFFIX = "|home"


def _sync_page(conn, db_path, table_name, course_id, page_summary, is_changed, is_home=False):
    prefixed_id = f"page:{page_summary['url']}"
    updated_at = page_summary.get("updated_at", "") + (HOME_SUFFIX if is_home else "")

    if is_changed:
        indexing.delete_ref_doc_nodes(db_path, table_name, prefixed_id)

    # Pages found via Modules or the front page were already fetched in full
    # (body included) to learn their updated_at; only list_pages summaries,
    # which never carry a body, need fetching here.
    full = page_summary if "body" in page_summary else canvas.get_page(course_id, page_summary["url"])
    title = (full or {}).get("title") or page_summary.get("title") or page_summary["url"]
    sections = ingestion.extract_html_sections((full or {}).get("body") or "")
    text = ingestion.sections_text(sections)
    # item_type="page": a Canvas wiki page isn't paginated like a PDF —
    # generation.py's citation formatting reads item_type back as
    # source_type, so this must say "page", not "file", and carries no
    # fabricated page number.
    nodes = indexing.sections_to_nodes(sections, f"Home: {title}" if is_home else title, prefixed_id, item_type="page")

    if nodes:
        indexing.add_nodes(nodes, db_path, table_name)
    sync.mark_synced(conn, prefixed_id, "page", title, updated_at, sync.content_hash(text))
    return title


def schedule_line(assignment: dict, tz: tzinfo | None = None) -> str:
    """"Due Tue, Sep 15, 2026 at 10:00 AM EDT. Worth 100 points." for an
    assignment, or "" when Canvas gives neither. A due date lives on the
    assignment record, not in its description, so without this line chat
    can't answer "when is X due?". tz defaults to the student's own (the
    backend runs on their machine), so the time reads the way Canvas shows it
    to them."""
    parts = []
    due_at = assignment.get("due_at")
    if due_at:
        try:
            due = datetime.fromisoformat(due_at.replace("Z", "+00:00")).astimezone(tz)
            parts.append(f"Due {due.strftime('%a, %b')} {due.day}, {due.year} at {due.strftime('%I:%M %p %Z').lstrip('0')}.")
        except ValueError:
            pass
    points = assignment.get("points_possible")
    if isinstance(points, (int, float)) and points > 0:
        parts.append(f"Worth {points:g} points.")
    return " ".join(parts)


def _sync_assignment(conn, db_path, table_name, assignment, is_changed):
    prefixed_id = f"assignment:{assignment['id']}"
    name = assignment.get("name") or f"Assignment {assignment['id']}"
    if is_changed:
        indexing.delete_ref_doc_nodes(db_path, table_name, prefixed_id)

    sections = ingestion.extract_html_sections(assignment.get("description") or "")
    schedule = schedule_line(assignment)
    if schedule:
        sections.insert(0, {"heading": "Due date and points", "text": schedule})
    text = ingestion.sections_text(sections)
    # Own item_type: citations.ts opens /assignments/<id>, and explain.py's
    # pointers exclude these (see build_pointers).
    nodes = indexing.sections_to_nodes(sections, name, prefixed_id, item_type="assignment")
    if nodes:
        indexing.add_nodes(nodes, db_path, table_name)
    sync.mark_synced(conn, prefixed_id, "assignment", name, assignment.get("updated_at", ""), sync.content_hash(text))
    return name


def _sync_syllabus(conn, db_path, table_name, course_id, syllabus_html, version, is_changed):
    prefixed_id = f"syllabus:{course_id}"
    if is_changed:
        indexing.delete_ref_doc_nodes(db_path, table_name, prefixed_id)

    sections = ingestion.extract_html_sections(syllabus_html)
    text = ingestion.sections_text(sections)
    # Own item_type so citations.ts can open Canvas's syllabus URL
    # (/assignments/syllabus), which isn't under /pages/.
    nodes = indexing.sections_to_nodes(sections, "Syllabus", prefixed_id, item_type="syllabus")
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


def _linked_file_ids(html: str, course_id: int) -> list[str]:
    """Ids of this course's files linked from a page, syllabus, assignment,
    announcement or discussion: "/courses/<id>/files/<n>" (Canvas's own
    links, also under /api/v1) or a bare "/files/<n>". Another course's or a
    user's files are left alone."""
    found = []
    for link_course, course_file, bare_file in _FILE_LINK_RE.findall(html or ""):
        if course_file and link_course == str(course_id):
            found.append(course_file)
        elif bare_file:
            found.append(bare_file)
    return list(dict.fromkeys(found))


_FILE_LINK_RE = re.compile(r"/courses/(\d+)/files/(\d+)|(?<![\d/])/files/(\d+)")


def _topic_text(topic: dict) -> str:
    message = (topic.get("message") or "").strip()
    return ingestion.extract_html_page(message).strip() if message else ""


def _topic_version(topic: dict) -> str:
    """Discussion topics carry no updated_at (always null on canvas.cmu.edu),
    so their text stands in, as for the syllabus."""
    return sync.content_hash(f"{topic.get('title') or ''}\n{topic.get('message') or ''}")


def _posted_line(topic: dict, tz: tzinfo | None = None) -> str:
    when = topic.get("posted_at") or topic.get("created_at")
    if not when:
        return ""
    try:
        posted = datetime.fromisoformat(when.replace("Z", "+00:00")).astimezone(tz)
    except ValueError:
        return ""
    return f"Posted {posted.strftime('%a, %b')} {posted.day}, {posted.year}."


def _sync_topic(conn, db_path, table_name, topic, kind, is_changed):
    """An announcement or a discussion's opening post (not the replies)."""
    prefixed_id = f"{kind}:{topic['id']}"
    title = (topic.get("title") or "").strip() or f"{kind.title()} {topic['id']}"
    if is_changed:
        indexing.delete_ref_doc_nodes(db_path, table_name, prefixed_id)
    sections = ingestion.extract_html_sections(topic.get("message") or "")
    posted = _posted_line(topic) if kind == "announcement" else ""
    if posted:
        sections.insert(0, {"heading": "Posted", "text": posted})
    text = ingestion.sections_text(sections)
    # Own item_type: citations.ts opens /discussion_topics/<id> for both.
    nodes = indexing.sections_to_nodes(sections, title, prefixed_id, item_type=kind)
    if nodes:
        indexing.add_nodes(nodes, db_path, table_name)
    sync.mark_synced(conn, prefixed_id, kind, title, _topic_version(topic), sync.content_hash(text))
    return title


def sync_course(course_id: int, sm_home: Path):
    """Serialize overlapping sync requests for the same course."""
    with _course_lock(sm_home, course_id):
        manifest_path, db_path = _course_paths(sm_home, course_id)
        conn = sync.open_manifest(manifest_path)
        try:
            yield from _sync_course_items(course_id, db_path, f"course_{course_id}", conn)
        except Exception as error:
            yield {"done": True, "error": str(error)}
        finally:
            conn.close()


def _sync_course_items(course_id: int, db_path: Path, table_name: str, conn):
    """Generator — see module docstring and the design spec for the full
    contract. Yields {"item", "status", "error"?} per processed item, then
    exactly one final {"done": True, "new", "changed", "removed", "failed"}
    summary, or {"done": True, "error": str} if the course couldn't be
    synced at all. Exactly one terminal ("done") event always fires, even
    if something unexpected blows up mid-stream — main.py has already sent
    the 200 and streaming headers by the time this generator's body runs,
    so an uncaught exception here would leave the connection dying
    mid-stream with no terminating event for the frontend to act on.

    Everything a student reaches from the course menu, not only Modules:
    Home, Syllabus, Pages, Assignments, Announcements, Discussions and Files.
    Files are found three ways: module items, the Files tab when the course
    shows it, and links in the text of all the others. 18-658 lists no files
    in its Modules; all 46 of its readings are links in its pages and
    syllabus."""
    try:
        structure = canvas.get_course_structure(course_id)
        pages_list = canvas.list_pages(course_id)
        front_page = canvas.get_front_page(course_id)
        syllabus_html = canvas.get_syllabus(course_id)
        assignments = canvas.list_assignments(course_id)
        files_tab = canvas.list_course_files(course_id)
        announcements = canvas.list_announcements(course_id)
        discussions = canvas.list_discussions(course_id)
    except (canvas.CanvasError, httpx.HTTPStatusError, httpx.TransportError) as e:
        yield {"done": True, "error": str(e)}
        return

    module_items = [item for module in structure for item in module.get("items", [])]

    new_count = changed_count = removed_count = failed_count = 0

    # Coarse safety net over the fine-grained per-item try/excepts below
    # (which still isolate one file/page's failure from the rest). Its only
    # job is the "exactly one terminal event, always" guarantee above —
    # sync.diff() and _sync_deleted()'s index/manifest writes are otherwise
    # unguarded, and an exception from either would escape uncaught.
    try:
        # Pages come from three places, merged by url slug. list_pages is
        # the Pages-tab listing, which 404s for students in most courses
        # (8 of 10 surveyed) — yet every Page item in those courses' Modules
        # opened fine individually (211 of 211), and five courses had no
        # other content at all. Module items carry no updated_at, so each
        # one is fetched in full here; the body is kept for _sync_page. A
        # fetch that fails or 404s is unresolved, not deleted — same guard
        # as files below.
        pages_by_url = {p["url"]: p for p in pages_list}
        if front_page and front_page.get("url"):
            pages_by_url.setdefault(front_page["url"], front_page)
        unresolved_page_ids: set[str] = set()
        module_page_urls = [item["page_url"] for item in module_items if item.get("type") == "Page" and item.get("page_url")]
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
        # Pages-tab summaries carry no body, and a page's links are needed
        # every sync (a file linked only from an unchanged page is still
        # there). A page whose body can't be read leaves its links unknown,
        # so no file is taken as deleted this round.
        links_complete = True
        for url, page in list(pages_by_url.items()):
            if "body" in page:
                continue
            try:
                full = canvas.get_page(course_id, url)
            except Exception as e:
                full = None
                yield {"item": url, "status": "failed", "error": str(e)}
                failed_count += 1
            if full is None:
                links_complete = False
                continue
            pages_by_url[url] = {**page, **full, "updated_at": page.get("updated_at", full.get("updated_at", ""))}
        home_url = front_page.get("url") if front_page else None
        page_remote = [
            {"id": f"page:{url}", "updated_at": p.get("updated_at", "") + (HOME_SUFFIX if url == home_url else "")}
            for url, p in pages_by_url.items()
        ]

        # The syllabus has no updated_at of its own: its content hash stands
        # in as the version, so an edit reads as "changed".
        syllabus_remote = []
        if syllabus_html and ingestion.extract_html_page(syllabus_html).strip():
            syllabus_remote = [{"id": f"syllabus:{course_id}", "updated_at": sync.content_hash(syllabus_html)}]

        # Assignment instructions, so chat can answer "what does Task 2 ask
        # for?" (Explain only ever read one assignment at a time) and "when is it
        # due?". Ones with neither text nor a due date or points are left out;
        # an assignment whose description was cleared then reads as deleted,
        # which matches what the student can see.
        assignments_by_id = {
            str(a["id"]): a
            for a in assignments
            if (a.get("description") and ingestion.extract_html_page(a["description"]).strip()) or schedule_line(a)
        }
        assignment_remote = [
            {"id": f"assignment:{aid}", "updated_at": a.get("updated_at", "")} for aid, a in assignments_by_id.items()
        ]

        # Announcements and discussions: the opening post only. Empty ones
        # (or a locked topic Canvas sends without its text) are left out.
        topics = {
            kind: {str(t["id"]): t for t in listing if t.get("id") is not None and _topic_text(t)}
            for kind, listing in (("announcement", announcements), ("discussion", discussions))
        }
        topic_remote = {
            kind: [{"id": f"{kind}:{tid}", "updated_at": _topic_version(t)} for tid, t in by_id.items()]
            for kind, by_id in topics.items()
        }

        # Files: module items, then the Files tab and attachments (which
        # come with their details), then links in every text above.
        page_links = {url: _linked_file_ids(p.get("body") or "", course_id) for url, p in pages_by_url.items()}
        other_html = [syllabus_html or ""] + [a.get("description") or "" for a in assignments]
        other_html += [t.get("message") or "" for t in [*announcements, *discussions]]
        known_metas = {str(f["id"]): f for f in files_tab if f.get("id") is not None}
        for topic in [*announcements, *discussions]:
            for attachment in topic.get("attachments") or []:
                if attachment.get("id") is not None:
                    known_metas.setdefault(str(attachment["id"]), attachment)
        wanted_ids = [str(item["content_id"]) for item in module_items if item.get("type") == "File" and item.get("content_id") is not None]
        wanted_ids += list(known_metas)
        wanted_ids += [fid for links in page_links.values() for fid in links]
        wanted_ids += [fid for html in other_html for fid in _linked_file_ids(html, course_id)]
        # A module File item with no content_id can't be looked up: counted
        # as failed, as before.
        for item in module_items:
            if item.get("type") == "File" and item.get("content_id") is None:
                failed_count += 1
                yield {"item": "?", "status": "failed", "error": "module file item has no content_id"}

        # Metadata collection itself can fail per-item (get_file hitting a
        # real Canvas/network error) — isolated here the same as the
        # extraction/indexing failures below, so one bad file doesn't abort
        # the whole course sync.
        file_metas = {}
        all_file_names: dict[str, str] = {}
        unresolved_file_ids: set[str] = set()
        for fid in dict.fromkeys(wanted_ids):
            prefixed_id = f"file:{fid}"
            meta = known_metas.get(fid)
            if meta is None:
                try:
                    meta = canvas.get_file(int(fid))
                except Exception as e:
                    failed_count += 1
                    unresolved_file_ids.add(prefixed_id)
                    yield {"item": fid, "status": "failed", "error": str(e)}
                    continue
            if meta is None:
                # get_file degraded a 403/404 to None — skip indexing it as
                # before, but record it as unresolved so its absence from
                # file_remote isn't mistaken for "deleted from Canvas".
                unresolved_file_ids.add(prefixed_id)
                continue
            display_name = meta.get("display_name", "")
            if Path(display_name).suffix.lower() not in SUPPORTED_FILE_SUFFIXES:
                print(f"[course_sync] skipping unsupported file: {display_name}")
                continue
            file_metas[str(meta["id"])] = meta
            all_file_names[str(meta["id"])] = display_name

        # A large file's version carries whether it's a preview or skipped
        # (large_files.version_suffix): the student turning it on or off
        # then reads as a change.
        file_suffix = {fid: large_files.version_suffix(conn, fid, meta.get("size") or 0) for fid, meta in file_metas.items()}
        file_remote = [
            {"id": f"file:{fid}", "updated_at": meta.get("updated_at", "") + file_suffix[fid]}
            for fid, meta in file_metas.items()
        ]

        # The course outline, for listing questions in chat (course_items.py).
        # Like the deletion guards below, an empty listing never wipes one
        # already saved: a hidden modules tab looks the same as no modules.
        outline = course_items.outline_rows(structure, page_links=page_links, file_names=all_file_names)
        if home_url:
            home_title = (front_page.get("title") or "").strip() or "Home"
            outline = course_items.group_rows("Home", [home_title], "page") + outline
        # By id, not name: a module item's title often isn't its file's name.
        in_modules = {str(item.get("content_id")) for item in module_items if item.get("type") == "File"}
        in_modules |= {fid for url in module_page_urls for fid in page_links.get(url, [])}
        module_topics = {str(item.get("content_id")) for item in module_items if item.get("type") == "Discussion"}
        outline += course_items.group_rows(
            "Other course files", sorted(n for fid, n in all_file_names.items() if fid not in in_modules), "file"
        )
        outline += course_items.group_rows(
            "Announcements", [(t.get("title") or "").strip() for t in announcements], "announcement"
        )
        outline += course_items.group_rows(
            "Discussions",
            [(t.get("title") or "").strip() for t in discussions if str(t.get("id")) not in module_topics],
            "discussion",
        )

        file_diff = sync.diff(conn, "file", file_remote)
        page_diff = sync.diff(conn, "page", page_remote)
        syllabus_diff = sync.diff(conn, "syllabus", syllabus_remote)
        assignment_diff = sync.diff(conn, "assignment", assignment_remote)
        topic_diffs = {kind: sync.diff(conn, kind, remote) for kind, remote in topic_remote.items()}

        file_deleted = _deletable(file_remote, file_diff["deleted"], unresolved_file_ids) if links_complete else []
        page_deleted = _deletable(page_remote, page_diff["deleted"], unresolved_page_ids)
        # Like the other empty-listing guards: a syllabus that comes back
        # empty or 403 is never taken as "removed".
        syllabus_deleted = _deletable(syllabus_remote, syllabus_diff["deleted"], set())
        assignment_deleted = _deletable(assignment_remote, assignment_diff["deleted"], set())
        topic_deleted = {
            kind: _deletable(topic_remote[kind], topic_diffs[kind]["deleted"], set()) for kind in topic_remote
        }

        deletions = [
            ("file", file_deleted),
            ("page", page_deleted),
            ("syllabus", syllabus_deleted),
            ("assignment", assignment_deleted),
            *topic_deleted.items(),
        ]
        for item_type, deleted_ids in deletions:
            for event in _sync_deleted(conn, db_path, table_name, item_type, deleted_ids):
                removed_count += 1
                yield event

        for ids, is_changed in ((file_diff["new"], False), (file_diff["changed"], True)):
            for prefixed_id in ids:
                fid = prefixed_id.removeprefix("file:")
                meta = file_metas[fid]
                try:
                    name = _sync_file(conn, db_path, table_name, meta, is_changed, file_suffix[fid])
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
                    title = _sync_page(conn, db_path, table_name, course_id, page_summary, is_changed, url == home_url)
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

        for ids, is_changed in ((assignment_diff["new"], False), (assignment_diff["changed"], True)):
            for prefixed_id in ids:
                assignment = assignments_by_id[prefixed_id.removeprefix("assignment:")]
                try:
                    name = _sync_assignment(conn, db_path, table_name, assignment, is_changed)
                    yield {"item": name, "status": "done"}
                    changed_count += is_changed
                    new_count += not is_changed
                except Exception as e:
                    failed_count += 1
                    yield {"item": assignment.get("name", prefixed_id), "status": "failed", "error": str(e)}

        for kind, diff in topic_diffs.items():
            for ids, is_changed in ((diff["new"], False), (diff["changed"], True)):
                for prefixed_id in ids:
                    topic = topics[kind][prefixed_id.removeprefix(f"{kind}:")]
                    try:
                        name = _sync_topic(conn, db_path, table_name, topic, kind, is_changed)
                        yield {"item": name, "status": "done"}
                        changed_count += is_changed
                        new_count += not is_changed
                    except Exception as e:
                        failed_count += 1
                        yield {"item": topic.get("title") or prefixed_id, "status": "failed", "error": str(e)}

        # Saved last, so a large file's line says what this sync indexed of it.
        if outline:
            labels = {r["name"]: large_files.outline_label(r) for r in large_files.rows(conn)}
            course_items.save_outline(conn, course_items.label_files(outline, labels))
    except Exception as e:
        yield {"done": True, "error": str(e)}
        return

    yield {"done": True, "new": new_count, "changed": changed_count, "removed": removed_count, "failed": failed_count}
