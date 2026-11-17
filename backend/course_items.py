"""The course outline behind chat's list_course_items tool (RAG gaps plan
task 8, docs/plans/2026-11-09-rag-course-gaps.md).

"What are all the readings for week 3?" can't be answered from a handful
of search results: search returns the passages most like the question, not
every item in a module. Canvas already says what's in each module, and the
sync fetches that structure (canvas.get_course_structure) to find files. It
is saved here as a flat outline in the course's manifest.db, so chat can
list a module, a section or a kind of item in full.

An outline row is a name, not content: the model may list names from it, but
what an item says still comes from search_course with citations.

Sub-headers (Canvas "SubHeader" items, such as "Readings" or "Unit Testing")
aren't items; they become the section of the items under them, until the
next sub-header or the end of the module.
"""

import re
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS outline (
  position  INTEGER PRIMARY KEY,
  module    TEXT NOT NULL,
  section   TEXT NOT NULL,
  title     TEXT NOT NULL,
  item_type TEXT NOT NULL,
  url       TEXT NOT NULL
);
"""

# Canvas module item types, as the student sees them.
ITEM_TYPES = {
    "File": "file",
    "Page": "page",
    "Assignment": "assignment",
    "Quiz": "quiz",
    "Discussion": "discussion",
    "ExternalUrl": "link",
    "ExternalTool": "tool",
}
# Plus announcements, which live outside Modules (course_sync's own group).
TYPE_NAMES = sorted({*ITEM_TYPES.values(), "announcement"})
# Enough for every item of the larger local course's modules at once (~100),
# small enough to stay a few thousand tokens.
MAX_ITEMS = 150


def _tidy(text) -> str:
    return " ".join(str(text or "").split())


def outline_rows(
    structure: list[dict], page_links: dict[str, list[str]] | None = None, file_names: dict[str, str] | None = None
) -> list[dict]:
    """`page_links` (page url -> linked file ids) and `file_names` (file id
    -> name) put the files a module's page links to right under that page,
    in a "Linked from <page>" section: 18-658's readings are such links, so
    "week 3" then finds them with the page."""
    page_links, file_names = page_links or {}, file_names or {}
    rows = []
    for module in structure:
        module_name = _tidy(module.get("name"))
        section = ""
        for item in module.get("items") or []:
            title = _tidy(item.get("title"))
            if not title:
                continue
            if item.get("type") == "SubHeader":
                section = title
                continue
            raw_type = str(item.get("type") or "item")
            rows.append(
                {
                    "module": module_name,
                    "section": section,
                    "title": title,
                    "item_type": ITEM_TYPES.get(raw_type, raw_type.lower()),
                    "url": str(item.get("external_url") or "") if raw_type == "ExternalUrl" else "",
                }
            )
            if raw_type == "Page":
                linked = [file_names[f] for f in page_links.get(item.get("page_url") or "", []) if f in file_names]
                rows += [
                    {"module": module_name, "section": f"Linked from {title}", "title": name, "item_type": "file", "url": ""}
                    for name in dict.fromkeys(linked)
                ]
    return rows


def group_rows(group: str, titles: list[str], item_type: str) -> list[dict]:
    """Rows for items outside Modules, under a group named like a module
    ("Announcements", "Other course files")."""
    return [
        {"module": group, "section": "", "title": _tidy(t), "item_type": item_type, "url": ""}
        for t in dict.fromkeys(titles)
        if _tidy(t)
    ]


def label_files(rows: list[dict], labels: dict[str, str]) -> list[dict]:
    """Adds large_files.py's note after a file's name ("About Face.pdf
    (first 150 of 722 pages synced)"), so a listing shows what's searchable."""
    return [
        {**r, "title": f"{r['title']} ({labels[r['title']]})"} if r["item_type"] == "file" and labels.get(r["title"]) else r
        for r in rows
    ]


def save_outline(conn: sqlite3.Connection, rows: list[dict]) -> None:
    """Replaces the whole outline: modules have no ids or dates worth
    diffing, and the listing is cheap to rewrite."""
    with conn:
        conn.execute(SCHEMA)
        conn.execute("DELETE FROM outline")
        conn.executemany(
            "INSERT INTO outline (position, module, section, title, item_type, url) VALUES (?, ?, ?, ?, ?, ?)",
            [(i, r["module"], r["section"], r["title"], r["item_type"], r["url"]) for i, r in enumerate(rows)],
        )


def load_outline(conn: sqlite3.Connection) -> list[dict]:
    if not _has_table(conn, "outline"):
        return []
    cursor = conn.execute("SELECT module, section, title, item_type, url FROM outline ORDER BY position")
    return [dict(zip(("module", "section", "title", "item_type", "url"), row)) for row in cursor]


def _has_table(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)).fetchone() is not None


def _word_pattern(words: list[str]) -> re.Pattern:
    """Whole words, case-insensitive, a plural "s" either way: "week 3"
    finds "Week 3: Elicitation" but not "Week 30"."""
    parts = []
    for word in words:
        stem = word[:-1] if len(word) > 3 and word.lower().endswith("s") else word
        parts.append(re.escape(stem) + "s?")
    return re.compile(r"(?<!\w)" + r"\s+".join(parts) + r"(?!\w)", re.IGNORECASE)


def _matches(rows: list[dict], topic: str) -> list[dict]:
    """The topic as a phrase in the module, section or title first. When
    that finds nothing, every word anywhere in them: the model asks for
    "sprint deliverables" when "Sprint" is in the item names and
    "Deliverables" in the module's (listing eval, 56350)."""
    words = topic.split()
    if not words:
        return rows
    phrase = _word_pattern(words)
    hits = [r for r in rows if any(phrase.search(r[k]) for k in ("module", "section", "title"))]
    if hits:
        return hits
    each = [_word_pattern([w]) for w in words]
    return [r for r in rows if all(p.search(f"{r['module']} | {r['section']} | {r['title']}") for p in each)]


def _item_line(row: dict) -> str:
    kind = f"link: {row['url']}" if row["item_type"] == "link" and row["url"] else row["item_type"]
    return f"- {row['title']} ({kind})"


def format_listing(rows: list[dict], topic: str = "", types: list[str] | None = None) -> str:
    wanted = {t.lower() for t in types or []}
    hits = _matches([r for r in rows if not wanted or r["item_type"] in wanted], topic)
    asked = " and ".join(part for part in (f'"{topic}"' if topic.strip() else "", ", ".join(sorted(wanted))) if part)
    if not hits:
        modules = list(dict.fromkeys(r["module"] for r in rows if r["module"]))
        return f"Nothing in the course's modules matches {asked or 'that'}. Modules in this course: " + "; ".join(modules)

    shown = hits[:MAX_ITEMS]
    lines = [f"Course modules on Canvas: {len(hits)} items" + (f" matching {asked}" if asked else "") + "."]
    module = section = None
    for row in shown:
        if row["module"] != module:
            module, section = row["module"], ""
            lines.append(f"\nModule: {module or '(no module name)'}")
        if row["section"] != section:
            section = row["section"]
            lines.append(f"  {section}:")
        lines.append(("    " if section else "  ") + _item_line(row))
    if len(hits) > len(shown):
        lines.append(f"\n{len(hits) - len(shown)} more not shown. Ask again with a topic or types to narrow it.")
    return "\n".join(lines)


def _manifest_rows(conn: sqlite3.Connection) -> list[dict]:
    """Before a course's outline is saved (synced before this existed, or
    its modules tab is hidden), the indexed items' names, ungrouped."""
    if not _has_table(conn, "manifest"):
        return []
    cursor = conn.execute(
        "SELECT display_name, item_type FROM manifest WHERE item_type IN ('file', 'page', 'assignment') ORDER BY item_type, display_name"
    )
    return [{"module": "", "section": "", "title": _tidy(name), "item_type": kind, "url": ""} for name, kind in cursor]


def list_for_course(sm_home: Path, course_id: int, topic: str = "", types: list[str] | None = None) -> str:
    path = Path(sm_home) / "courses" / str(course_id) / "manifest.db"
    if not path.exists():
        return "This course hasn't been synced yet, so there's no list of its materials."
    # Read-only: answering a question must never create or change the manifest.
    conn = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
    try:
        rows = load_outline(conn)
        if rows:
            return format_listing(rows, topic, types)
        fallback = _manifest_rows(conn)
    finally:
        conn.close()
    if not fallback:
        return "This course hasn't been synced yet, so there's no list of its materials."
    return (
        "The course's module outline isn't saved yet (it is on the next sync), so this list is not grouped by "
        "module or week; it's every file, page and assignment the course search covers.\n"
        + format_listing(fallback, topic, types)
    )
