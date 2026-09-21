"""Sync mechanism — implementation-plan.md Step 7, design spec §5.5.

Diffs a course's current Canvas listing (ID + updated_at, cheap metadata
only) against manifest.db (data-model.md §4) into new/changed/deleted/
unchanged buckets. Runs once per app launch, not a background daemon —
no separate scheduler needed.

diff() takes an already-fetched remote listing rather than calling
canvas.py itself, so it's testable against simulated Canvas data without
live access — the caller (wherever real sync gets orchestrated) is
responsible for the actual Canvas calls.
"""

import hashlib
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS manifest (
  canvas_item_id    TEXT NOT NULL,
  item_type         TEXT NOT NULL,
  display_name      TEXT NOT NULL,
  canvas_updated_at TEXT NOT NULL,
  content_hash      TEXT NOT NULL,
  last_synced_at    TEXT NOT NULL,
  PRIMARY KEY (canvas_item_id, item_type)
);
"""


def open_manifest(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute(SCHEMA)
    conn.commit()
    return conn


def content_hash(text: str) -> str:
    """Hash of extracted text, not raw bytes (design spec §5.5) — a
    metadata-only touch (rename, permission change) shouldn't trigger
    re-embedding if the actual content is unchanged."""
    return hashlib.sha256(text.encode()).hexdigest()


def raw_bytes_hash(data: bytes) -> str:
    """Fast pre-check before extraction (design spec §5.5) — identical
    bytes skip extraction entirely, since extraction/embedding are the
    expensive steps, not the metadata diff."""
    return hashlib.sha256(data).hexdigest()


def diff(conn: sqlite3.Connection, item_type: str, remote_items: list[dict]) -> dict[str, list[str]]:
    """remote_items: [{"id": str, "updated_at": str}, ...]. Sorts every
    item into exactly one bucket per design spec §5.5."""
    rows = conn.execute(
        "SELECT canvas_item_id, canvas_updated_at FROM manifest WHERE item_type = ?", (item_type,)
    ).fetchall()
    manifest_map = dict(rows)
    remote_map = {item["id"]: item["updated_at"] for item in remote_items}

    return {
        "new": [i for i in remote_map if i not in manifest_map],
        "changed": [i for i in remote_map if i in manifest_map and remote_map[i] != manifest_map[i]],
        "deleted": [i for i in manifest_map if i not in remote_map],
        "unchanged": [i for i in remote_map if i in manifest_map and remote_map[i] == manifest_map[i]],
    }


def mark_synced(
    conn: sqlite3.Connection,
    canvas_item_id: str,
    item_type: str,
    display_name: str,
    canvas_updated_at: str,
    hash_: str,
):
    conn.execute(
        """INSERT INTO manifest (canvas_item_id, item_type, display_name, canvas_updated_at, content_hash, last_synced_at)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT (canvas_item_id, item_type) DO UPDATE SET
             display_name = excluded.display_name,
             canvas_updated_at = excluded.canvas_updated_at,
             content_hash = excluded.content_hash,
             last_synced_at = excluded.last_synced_at""",
        (canvas_item_id, item_type, display_name, canvas_updated_at, hash_, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()


def forget(conn: sqlite3.Connection, canvas_item_id: str, item_type: str):
    conn.execute("DELETE FROM manifest WHERE canvas_item_id = ? AND item_type = ?", (canvas_item_id, item_type))
    conn.commit()


def get_content_hash(conn: sqlite3.Connection, canvas_item_id: str, item_type: str) -> str | None:
    row = conn.execute(
        "SELECT content_hash FROM manifest WHERE canvas_item_id = ? AND item_type = ?",
        (canvas_item_id, item_type),
    ).fetchone()
    return row[0] if row else None
