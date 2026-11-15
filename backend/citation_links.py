"""Canvas links for citations (plan Decision 11).

The same URL shapes as the app's app/src/citations.ts, so a citation in
Claude Code opens the page a citation in the app opens. Built here, in
Python, because in a terminal "lecture3.pdf · p.12" alone is hard to open.

course_sync.py prefixes every indexed item's id by type ("file:12345",
"page:week-1-overview", "assignment:998240", "syllabus:55016"); the prefix
comes off before the id goes into the URL. Class recordings made in the app
("transcript", "notes") are local and have no Canvas page.
"""

from pathlib import Path

import config

# canvas.py's own default when nothing is configured.
DEFAULT_ORIGIN = "https://canvas.cmu.edu"
NO_CANVAS_PAGE = {"transcript", "notes"}


def canvas_origin(sm_home: Path) -> str:
    raw = config.read_config(sm_home).get("canvas_base_url") or ""
    return config.normalize_canvas_base_url(raw) or DEFAULT_ORIGIN


def canvas_url(origin: str, course_id: int, item_type: str | None, item_id: str) -> str | None:
    if item_type in NO_CANVAS_PAGE or not item_id:
        return None
    base = f"{origin}/courses/{course_id}"
    if item_type == "syllabus":
        return f"{base}/assignments/syllabus"  # Canvas serves it under assignments, not /pages/
    if item_type == "assignment":
        return f"{base}/assignments/{item_id.removeprefix('assignment:')}"
    if item_type == "page":
        return f"{base}/pages/{item_id.removeprefix('page:')}"
    return f"{base}/files/{item_id.removeprefix('file:')}"
