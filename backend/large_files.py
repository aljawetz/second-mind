"""Large files wait for the student (RAG gaps plan, task 8 follow-up).

The first sync after the whole course menu was read took 14.4 minutes for
18-658, and two whole textbooks took about 7.5 of them. So:

- a PDF over MAX_PDF_PAGES pages gets its first MAX_PDF_PAGES indexed, as a
  labeled preview ("About Face.pdf (first 150 of 722 pages)"), so chat can
  say it only has part of the book instead of "not covered";
- any other file whose text is over MAX_TEXT_CHARS (about a 150-page PDF)
  gets a preview of that length: a Word file has no fixed pages;
- a file over MAX_FILE_BYTES isn't downloaded at all.

The student can turn any of them on in Manage courses, and the next sync
indexes the whole file.

How the next sync notices: course_sync adds version_suffix() to the file's
version in the manifest ("|preview" or "|skipped"). Turning a file on drops
the suffix, so its version no longer matches and it reads as changed;
turning it off puts the suffix back. Nothing else in the sync changes.
"""

import sqlite3

MAX_FILE_BYTES = 50_000_000
MAX_PDF_PAGES = 150
MAX_TEXT_CHARS = 450_000

SCHEMA = """
CREATE TABLE IF NOT EXISTS large_files (
  file_id   TEXT PRIMARY KEY,
  name      TEXT NOT NULL,
  size      INTEGER NOT NULL,
  pages     INTEGER,
  chars     INTEGER,
  long      INTEGER NOT NULL,
  state     TEXT NOT NULL,
  want_full INTEGER NOT NULL DEFAULT 0
);
"""
# state: "preview" (part indexed), "none" (too big to download), "full"
# (turned on and indexed whole). long: over the page or text limit when last
# read, so the next sync keeps it a preview without downloading it again.
FIELDS = ("file_id", "name", "size", "pages", "chars", "state", "want_full")


def _ensure(conn: sqlite3.Connection) -> None:
    conn.execute(SCHEMA)


def _row(conn: sqlite3.Connection, file_id: str) -> tuple | None:
    _ensure(conn)
    return conn.execute("SELECT long, want_full FROM large_files WHERE file_id = ?", (file_id,)).fetchone()


def wants_full(conn: sqlite3.Connection, file_id: str) -> bool:
    row = _row(conn, file_id)
    return bool(row and row[1])


def version_suffix(conn: sqlite3.Connection, file_id: str, size: int) -> str:
    row = _row(conn, file_id)
    if row and row[1]:
        return ""
    if size > MAX_FILE_BYTES:
        return "|skipped"
    if row and row[0]:
        return "|preview"
    return ""


def record(
    conn: sqlite3.Connection, file_id: str, name: str, size: int, *, pages: int | None, chars: int | None, long: bool, state: str
) -> None:
    """Keeps the student's choice (want_full) across syncs."""
    _ensure(conn)
    with conn:
        conn.execute(
            """INSERT INTO large_files (file_id, name, size, pages, chars, long, state) VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT (file_id) DO UPDATE SET name = excluded.name, size = excluded.size, pages = excluded.pages,
               chars = excluded.chars, long = excluded.long, state = excluded.state""",
            (file_id, name, size, pages, chars, int(long), state),
        )


def forget(conn: sqlite3.Connection, file_id: str) -> None:
    """The file is gone from Canvas, or no longer over any limit."""
    _ensure(conn)
    with conn:
        conn.execute("DELETE FROM large_files WHERE file_id = ?", (file_id,))


def set_want_full(conn: sqlite3.Connection, file_id: str, full: bool) -> bool:
    """False when the file isn't a large one (nothing to turn on)."""
    _ensure(conn)
    with conn:
        cursor = conn.execute("UPDATE large_files SET want_full = ? WHERE file_id = ?", (int(full), file_id))
    return cursor.rowcount > 0


def rows(conn: sqlite3.Connection) -> list[dict]:
    _ensure(conn)
    cursor = conn.execute(f"SELECT {', '.join(FIELDS)} FROM large_files ORDER BY name")
    return [{**dict(zip(FIELDS, row)), "want_full": bool(row[-1])} for row in cursor]


def preview_source(name: str, pages: int | None) -> str:
    """The source name a preview's chunks carry, so search results and
    citations say they're only part of the file."""
    if pages:
        return f"{name} (first {MAX_PDF_PAGES} of {pages} pages)"
    return f"{name} (first part)"


def outline_label(row: dict) -> str:
    """What the course outline adds after a large file's name, or ""."""
    if row["state"] == "preview":
        return f"first {MAX_PDF_PAGES} of {row['pages']} pages synced" if row["pages"] else "first part synced"
    if row["state"] == "none":
        return f"not synced: {row['size'] / 1_000_000:.0f} MB"
    return ""
