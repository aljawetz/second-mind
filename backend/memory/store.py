"""SQLite storage for agent memory — design spec §4.

One file per course (~/.secondmind/courses/<id>/memory.db). SQLite rather
than LanceDB, which course search uses: memory rows change all the time
(superseded, archived, access counts), which SQLite does in transactions
and LanceDB is built for appending; and a course's memory is a few thousand
rows at most, so a brute-force cosine scan in numpy takes milliseconds.

No LLM calls and no clock here: every time is passed in, so the evaluation
can replay a dated semester.
"""

import re
import sqlite3
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import numpy as np

KINDS = ("fact", "event", "task", "summary")
# A chat's summary (design spec §5.6) matters less than any one thing the
# student said in it: recall's importance weight settles close calls
# towards the specific memory.
SUMMARY_IMPORTANCE = 2

_SCHEMA = """
CREATE TABLE IF NOT EXISTS memory (
  id              TEXT PRIMARY KEY,
  kind            TEXT NOT NULL,
  text            TEXT NOT NULL,
  importance      INTEGER NOT NULL,
  event_time      TEXT,
  created_at      TEXT NOT NULL,
  valid_to        TEXT,
  superseded_by   TEXT REFERENCES memory(id) ON DELETE SET NULL,
  status          TEXT NOT NULL DEFAULT 'active',
  task_ref        TEXT,
  conversation_id TEXT,
  access_count    INTEGER NOT NULL DEFAULT 0,
  last_accessed   TEXT,
  embedding       BLOB NOT NULL
);
CREATE TABLE IF NOT EXISTS provenance (
  memory_id       TEXT NOT NULL REFERENCES memory(id) ON DELETE CASCADE,
  conversation_id TEXT NOT NULL,
  turn_index      INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS entity (id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL);
CREATE TABLE IF NOT EXISTS memory_entity (
  memory_id TEXT NOT NULL REFERENCES memory(id) ON DELETE CASCADE,
  entity_id INTEGER NOT NULL REFERENCES entity(id),
  PRIMARY KEY (memory_id, entity_id)
);
-- Written in the same transaction as memory, not an external-content
-- table kept in sync by triggers: simpler, and nothing to drift.
CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(memory_id UNINDEXED, text);
-- Every lifecycle decision, for debugging and for the evaluation's failure
-- analysis. reason is a label ("consolidation"), never memory text.
CREATE TABLE IF NOT EXISTS ops_log (at TEXT NOT NULL, op TEXT NOT NULL, memory_id TEXT, reason TEXT NOT NULL);
-- A turn the student forgot: the worker must not re-extract it (design spec §12).
CREATE TABLE IF NOT EXISTS forget_turn (
  conversation_id TEXT NOT NULL,
  turn_index      INTEGER NOT NULL,
  PRIMARY KEY (conversation_id, turn_index)
);
"""

# Words only. Quotes, NOT, *, : and - are FTS5 query syntax, and the
# student's raw question passed straight to MATCH raises "fts5: syntax error".
_WORD = re.compile(r"\w+")

# Words that match (nearly) every memory, so they say nothing about which
# one a question is about. "student" is here because every memory is
# written "The student …" (extract.py's prompt). Without this list, any
# question containing "the" or "is" keyword-matched every memory, and
# recall, which counts a keyword match by rank alone, returned five
# unrelated memories on every chat turn.
_STOPWORDS = frozenset(
    """a about after again all also am an and any are as at be been before being both but by can could
    d did do does doing done for from get got had has have having he her here hers him his how i if in into
    is it its just ll m me more most my no nor not now of off on once only or other our out over own re s
    said same say says she should so some student students such t than that the their them then there these
    they this those through to too under until up us ve very was we were what when where which while who
    whom why will with would you your""".split()
)


@dataclass
class Memory:
    id: str
    kind: str
    text: str
    importance: int
    event_time: datetime | None
    created_at: datetime
    valid_to: datetime | None
    superseded_by: str | None
    status: str
    task_ref: str | None
    conversation_id: str | None
    access_count: int
    last_accessed: datetime | None
    embedding: list[float]
    entities: list[str] = field(default_factory=list)
    provenance: list[tuple[str, int]] = field(default_factory=list)


def _iso(t: datetime | None) -> str | None:
    return t.isoformat() if t is not None else None


def _time(s: str | None) -> datetime | None:
    return datetime.fromisoformat(s) if s is not None else None


class MemoryStore:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        # One connection per store, shared by whichever thread holds _lock:
        # the background worker and request threads can each have a store
        # open on the same file, and WAL lets them read while one writes.
        self._conn = sqlite3.connect(path, check_same_thread=False, timeout=10)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        with self._lock, self._conn:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            # Deleted rows are zeroed, not left in free pages (see delete()).
            self._conn.execute("PRAGMA secure_delete=ON")
            self._conn.executescript(_SCHEMA)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # Python 3.13+ warns (ResourceWarning) about a connection that's garbage
    # collected without being closed; `with MemoryStore(...)` closes it.
    def __enter__(self) -> "MemoryStore":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def add(
        self,
        *,
        kind: str,
        text: str,
        importance: int,
        embedding: list[float],
        created_at: datetime,
        event_time: datetime | None = None,
        entities: list[str] = (),
        provenance: list[tuple[str, int]] = (),
        conversation_id: str | None = None,
        task_ref: str | None = None,
        reason: str = "",
    ) -> str:
        if kind not in KINDS:
            raise ValueError(f"unknown memory kind {kind!r}")
        memory_id = "m-" + uuid.uuid4().hex[:12]
        blob = np.asarray(embedding, dtype=np.float32).tobytes()
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO memory (id, kind, text, importance, event_time, created_at, task_ref, conversation_id, embedding)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (memory_id, kind, text, importance, _iso(event_time), _iso(created_at), task_ref, conversation_id, blob),
            )
            self._conn.execute("INSERT INTO memory_fts (memory_id, text) VALUES (?, ?)", (memory_id, text))
            for name in {e.strip().lower() for e in entities if e.strip()}:
                self._conn.execute("INSERT OR IGNORE INTO entity (name) VALUES (?)", (name,))
                self._conn.execute(
                    "INSERT INTO memory_entity (memory_id, entity_id) SELECT ?, id FROM entity WHERE name = ?",
                    (memory_id, name),
                )
            self._conn.executemany(
                "INSERT INTO provenance (memory_id, conversation_id, turn_index) VALUES (?, ?, ?)",
                [(memory_id, cid, turn) for cid, turn in provenance],
            )
            self._log(created_at, "ADD", memory_id, reason)
        return memory_id

    def set_summary(self, conversation_id: str, *, text: str, embedding: list[float], at: datetime, turn_index: int) -> str:
        """A chat's summary memory, one per chat, rewritten in place as the
        chat goes on. Its event_time is the latest turn, so it fades from
        when the chat was last active; a faded one comes back if the chat
        goes on."""
        with self._lock:
            row = self._conn.execute(
                "SELECT id FROM memory WHERE kind = 'summary' AND conversation_id = ?", (conversation_id,)
            ).fetchone()
            if row is None:
                return self.add(
                    kind="summary", text=text, importance=SUMMARY_IMPORTANCE, embedding=embedding,
                    created_at=at, event_time=at, provenance=[(conversation_id, turn_index)],
                    conversation_id=conversation_id, reason="summary",
                )
            memory_id = row["id"]
            with self._conn:
                self._conn.execute(
                    "UPDATE memory SET text = ?, embedding = ?, event_time = ?, status = 'active' WHERE id = ?",
                    (text, np.asarray(embedding, dtype=np.float32).tobytes(), _iso(at), memory_id),
                )
                self._conn.execute("DELETE FROM memory_fts WHERE memory_id = ?", (memory_id,))
                self._conn.execute("INSERT INTO memory_fts (memory_id, text) VALUES (?, ?)", (memory_id, text))
                self._conn.execute(
                    "INSERT INTO provenance (memory_id, conversation_id, turn_index) VALUES (?, ?, ?)",
                    (memory_id, conversation_id, turn_index),
                )
                self._log(at, "UPDATE", memory_id, "summary")
            return memory_id

    def get(self, memory_id: str) -> Memory | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM memory WHERE id = ?", (memory_id,)).fetchone()
            if row is None:
                return None
            return self._to_memory(row)

    def supersede(self, memory_id: str, *, by: str, valid_to: datetime, reason: str = "") -> None:
        """A newer memory replaces this one. It is kept, dated, for "what
        was it before?" questions, and left out of normal searches."""
        with self._lock, self._conn:
            self._conn.execute(
                "UPDATE memory SET valid_to = ?, superseded_by = ? WHERE id = ?", (_iso(valid_to), by, memory_id)
            )
            self._log(valid_to, "SUPERSEDE", memory_id, reason)

    def invalidate(self, memory_id: str, *, valid_to: datetime, reason: str = "") -> None:
        """The student took it back, with nothing to replace it."""
        with self._lock, self._conn:
            self._conn.execute("UPDATE memory SET valid_to = ? WHERE id = ?", (_iso(valid_to), memory_id))
            self._log(valid_to, "INVALIDATE", memory_id, reason)

    def archive(self, memory_id: str, *, at: datetime, reason: str = "") -> None:
        """Faded out (design spec §5.7): gone from every search, including
        history ones, but still listed for the student to see or delete."""
        with self._lock, self._conn:
            self._conn.execute("UPDATE memory SET status = 'archived' WHERE id = ?", (memory_id,))
            self._log(at, "ARCHIVE", memory_id, reason)

    def bump_importance(self, memory_id: str, *, at: datetime, reason: str = "") -> None:
        """Consolidation found the same thing again (NOOP): it matters more."""
        with self._lock, self._conn:
            self._conn.execute("UPDATE memory SET importance = MIN(importance + 1, 5) WHERE id = ?", (memory_id,))
            self._log(at, "BUMP", memory_id, reason)

    def revise(self, memory_id: str, *, text: str, embedding: list[float], at: datetime, reason: str = "") -> None:
        """Student corrected the wording in Manage memories: new text and
        embedding, FTS updated, stays active for recall."""
        blob = np.asarray(embedding, dtype=np.float32).tobytes()
        with self._lock, self._conn:
            updated = self._conn.execute(
                "UPDATE memory SET text = ?, embedding = ?, status = 'active' WHERE id = ? AND valid_to IS NULL",
                (text, blob, memory_id),
            ).rowcount
            if not updated:
                raise KeyError(memory_id)
            self._conn.execute("DELETE FROM memory_fts WHERE memory_id = ?", (memory_id,))
            self._conn.execute("INSERT INTO memory_fts (memory_id, text) VALUES (?, ?)", (memory_id, text))
            self._log(at, "UPDATE", memory_id, reason)

    def delete(self, memory_id: str, *, at: datetime, reason: str = "") -> None:
        """The student asked to forget it (design spec §5.7): really gone,
        not just hidden. Provenance and entity links cascade; a memory it
        had superseded stays superseded (ON DELETE SET NULL), so forgetting
        "we switched projects" doesn't bring the old project back.

        The DELETE log entry has no memory id: the memory's own log rows
        go too, and all that's left is that a deletion happened.

        Gone from the files, not just from queries. A plain DELETE left the
        text readable in the database files (test_memory_store.py's
        deleted_text test), in three places, each needing its own fix —
        confirmed by removing each one in turn:
        - freed pages keep the old bytes: secure_delete (in __init__);
        - FTS5 records a delete as a marker in a new index segment and keeps
          the old one, words included, until a merge: 'optimize' below;
        - the write-ahead log keeps the page as it was before the delete:
          the TRUNCATE checkpoint below. If another connection is mid-read
          the checkpoint can't finish, and the log is cleared at the next.
        """
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM memory_fts WHERE memory_id = ?", (memory_id,))
            self._conn.execute("INSERT INTO memory_fts (memory_fts) VALUES ('optimize')")
            self._conn.execute("DELETE FROM ops_log WHERE memory_id = ?", (memory_id,))
            self._conn.execute("DELETE FROM memory WHERE id = ?", (memory_id,))
            # An entity name only this memory used ("priya") is personal
            # data in its own right.
            self._conn.execute("DELETE FROM entity WHERE id NOT IN (SELECT entity_id FROM memory_entity)")
            self._log(at, "DELETE", None, reason)
        self._wal_checkpoint_truncate()

    def block_forget_turn(self, conversation_id: str, turn_index: int) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT OR IGNORE INTO forget_turn (conversation_id, turn_index) VALUES (?, ?)",
                (conversation_id, turn_index),
            )

    def is_turn_blocked(self, conversation_id: str, turn_index: int) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM forget_turn WHERE conversation_id = ? AND turn_index = ?",
                (conversation_id, turn_index),
            ).fetchone()
            return row is not None

    def _wal_checkpoint_truncate(self) -> None:
        for attempt in range(8):
            with self._lock:
                busy, _, _ = self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
            if not busy:
                return
            time.sleep(0.05 * (attempt + 1))
        print("memory store: wal_checkpoint(TRUNCATE) still busy after retries", file=sys.stderr)

    def touch(self, memory_ids: list[str], *, at: datetime) -> None:
        """Recall used these. Not logged: it happens on every question, and
        access_count/last_accessed already record it."""
        with self._lock, self._conn:
            self._conn.executemany(
                "UPDATE memory SET access_count = access_count + 1, last_accessed = ? WHERE id = ?",
                [(_iso(at), mid) for mid in memory_ids],
            )

    def add_provenance(self, memory_id: str, provenance: list[tuple[str, int]]) -> None:
        """The student said it again (consolidation's NOOP). Recorded so
        that deleting the first chat doesn't take a fact they also said in
        another one (memories_only_from)."""
        with self._lock, self._conn:
            self._conn.executemany(
                "INSERT INTO provenance (memory_id, conversation_id, turn_index) VALUES (?, ?, ?)",
                [(memory_id, cid, turn) for cid, turn in provenance],
            )

    def memories_only_from(self, conversation_id: str) -> list[str]:
        """What deleting this chat takes with it (design spec §5.7): memories
        every one of whose source turns is in it, plus its summary. A fact
        the student also said in another chat stays."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT memory_id FROM provenance GROUP BY memory_id"
                " HAVING SUM(conversation_id != ?) = 0"
                " UNION SELECT id FROM memory WHERE conversation_id = ?",
                (conversation_id, conversation_id),
            ).fetchall()
        return [r[0] for r in rows]

    def list_memories(self, include_inactive: bool = False) -> list[Memory]:
        """For the memory endpoint, newest first. include_inactive adds the
        superseded, taken-back and archived ones, so the student can see
        and delete everything held about them."""
        where = "" if include_inactive else "WHERE status = 'active' AND valid_to IS NULL"
        with self._lock:
            rows = self._conn.execute(f"SELECT * FROM memory {where} ORDER BY created_at DESC, rowid DESC").fetchall()
            return [self._to_memory(r) for r in rows]

    def ops(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute("SELECT at, op, memory_id, reason FROM ops_log ORDER BY rowid").fetchall()
        return [{"at": _time(r["at"]), "op": r["op"], "memory_id": r["memory_id"], "reason": r["reason"]} for r in rows]

    def _log(self, at: datetime, op: str, memory_id: str | None, reason: str) -> None:
        self._conn.execute(
            "INSERT INTO ops_log (at, op, memory_id, reason) VALUES (?, ?, ?, ?)", (_iso(at), op, memory_id, reason)
        )

    def vector_search(
        self, query: list[float], k: int, kinds: tuple[str, ...] = KINDS, include_history: bool = False
    ) -> list[tuple[Memory, float]]:
        """Top k by cosine similarity, highest first. A full scan: a
        course's memory is a few thousand rows, a few milliseconds."""
        where, params = self._filter(kinds, include_history)
        with self._lock:
            rows = self._conn.execute(f"SELECT * FROM memory m WHERE {where}", params).fetchall()
            if not rows:
                return []
            matrix = np.stack([np.frombuffer(r["embedding"], dtype=np.float32) for r in rows])
            q = np.asarray(query, dtype=np.float32)
            norms = np.linalg.norm(matrix, axis=1) * np.linalg.norm(q)
            scores = matrix @ q / np.where(norms == 0, 1.0, norms)
            top = np.argsort(-scores, kind="stable")[:k]
            return [(self._to_memory(rows[i]), float(scores[i])) for i in top]

    def keyword_search(
        self, query: str, k: int, kinds: tuple[str, ...] = KINDS, include_history: bool = False
    ) -> list[tuple[Memory, float]]:
        """Top k by BM25, best first. Scores are only comparable within one
        search (design spec §5.5), so callers should use the rank."""
        words = [w for w in _WORD.findall(query.lower()) if w not in _STOPWORDS]
        if not words:
            return []
        match = " OR ".join(f'"{w}"' for w in words)
        where, params = self._filter(kinds, include_history)
        with self._lock:
            rows = self._conn.execute(
                f"SELECT m.*, -bm25(memory_fts) AS score FROM memory_fts JOIN memory m ON m.id = memory_fts.memory_id"
                f" WHERE memory_fts MATCH ? AND {where} ORDER BY score DESC LIMIT ?",
                (match, *params, k),
            ).fetchall()
            return [(self._to_memory(r), r["score"]) for r in rows]

    @staticmethod
    def _filter(kinds: tuple[str, ...], include_history: bool) -> tuple[str, list]:
        where = f"m.status = 'active' AND m.kind IN ({','.join('?' * len(kinds))})"
        if not include_history:
            where += " AND m.valid_to IS NULL"
        return where, list(kinds)

    def _to_memory(self, row: sqlite3.Row) -> Memory:
        entities = [
            r["name"]
            for r in self._conn.execute(
                "SELECT e.name FROM memory_entity me JOIN entity e ON e.id = me.entity_id WHERE me.memory_id = ?",
                (row["id"],),
            )
        ]
        provenance = [
            (r["conversation_id"], r["turn_index"])
            for r in self._conn.execute(
                "SELECT conversation_id, turn_index FROM provenance WHERE memory_id = ? ORDER BY rowid", (row["id"],)
            )
        ]
        return Memory(
            id=row["id"],
            kind=row["kind"],
            text=row["text"],
            importance=row["importance"],
            event_time=_time(row["event_time"]),
            created_at=_time(row["created_at"]),
            valid_to=_time(row["valid_to"]),
            superseded_by=row["superseded_by"],
            status=row["status"],
            task_ref=row["task_ref"],
            conversation_id=row["conversation_id"],
            access_count=row["access_count"],
            last_accessed=_time(row["last_accessed"]),
            embedding=np.frombuffer(row["embedding"], dtype=np.float32).tolist(),
            entities=entities,
            provenance=provenance,
        )
