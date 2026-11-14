"""MCP server for the Second Mind Claude Code plugin (M0 spike of
docs/plans/2026-11-13-claude-code-plugin.md).

Claude Code is the LLM. This server only searches: no tool here calls a
model. Two tools for now:
- list_courses: the courses indexed on this machine, with their last sync.
- search_course_material: the same HybridRetriever the app's chat uses
  (chat.make_search: hybrid search, rank fusion, reranker, 0.5 cutoff),
  returning whole chunks with their citation labels.

It reads the index the app already built (SM_HOME, default ~/.secondmind,
the same rule as main.py). Models load on the first search, not at
startup, so a session that never asks about a course costs almost nothing
(plan Decision 7).

stdout is the MCP protocol channel. mcp's stdio_server moves fd 1 to stderr
while it owns the channel, so a stray print from a backend module lands in
stderr instead of breaking the protocol; logging goes to stderr too.

Run: uv run --extra mcp python mcp_server.py
"""

import datetime
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Callable

from mcp.server import MCPServer

import canvas
import indexing
import sync

logger = logging.getLogger("sm-mcp")

# The app's chat cutoff (main.CHAT_SIMILARITY_CUTOFF), copied rather than
# imported: main.py starts the app's HTTP server machinery on import.
SIMILARITY_CUTOFF = 0.5
DEFAULT_K = 5
MAX_K = 10

INSTRUCTIONS = (
    "Second Mind searches the student's own Canvas course materials (slides, readings, syllabus, "
    "assignments, Canvas pages). For any question about a course the student takes, call "
    "search_course_material before answering, even when you think you know. For a follow-up, search "
    "with a stand-alone version of the question. Course facts come only from the results, cited with "
    "their source label. Use list_courses to find the course id."
)


def sm_home() -> Path:
    return Path(os.environ.get("SM_HOME", str(Path.home() / ".secondmind")))


def today() -> datetime.date:
    """SM_TODAY (YYYY-MM-DD) pins the date relative-date expansion uses, so an
    eval run matches the app eval's fixed date. Unset: the real date."""
    pinned = os.environ.get("SM_TODAY")
    return datetime.date.fromisoformat(pinned) if pinned else datetime.date.today()


def _table(course_id: int) -> str:
    return f"course_{course_id}"


def indexed_course_ids(home: Path) -> list[int]:
    db_path = home / "index.lancedb"
    if not db_path.exists():
        return []
    import lancedb

    ids = []
    for name in lancedb.connect(str(db_path)).table_names():
        prefix, _, rest = name.partition("_")
        if prefix == "course" and rest.isdigit():
            ids.append(int(rest))
    return sorted(ids)


def last_synced_at(home: Path, course_id: int) -> str | None:
    manifest = home / "courses" / str(course_id) / "manifest.db"
    if not manifest.exists():
        return None
    conn = sync.open_manifest(manifest)
    try:
        row = conn.execute("SELECT MAX(last_synced_at) FROM manifest").fetchone()
    finally:
        conn.close()
    return row[0] if row else None


def canvas_course_names() -> dict[int, str]:
    """Course names live only in Canvas (config.json keeps ids). Best effort:
    without a token or a network, courses are listed by id alone."""
    try:
        return {c["id"]: c["name"] for c in canvas.list_courses() if c.get("name")}
    except Exception as e:  # no token, offline, Canvas down: names are a nicety here
        logger.warning("could not read course names from Canvas: %s", e)
        return {}


def list_courses_result(home: Path, names_for: Callable[[], dict[int, str]] = canvas_course_names) -> dict:
    ids = indexed_course_ids(home)
    names = names_for() if ids else {}
    return {
        "courses": [
            {"course_id": cid, "name": names.get(cid), "last_synced_at": last_synced_at(home, cid)}
            for cid in ids
        ]
    }


def _retriever_factory(home: Path):
    def make(course_id: int):
        import generation

        index = indexing.load_index(home / "index.lancedb", _table(course_id))
        return generation.HybridRetriever(index, similarity_cutoff=SIMILARITY_CUTOFF)

    return make


def _log_query(course_id: int, query: str, results: list[dict], seconds: float) -> None:
    """With SM_QUERY_LOG set, append each search as one JSON line: what
    Claude asked and what came back. The eval (ask_modes_eval.py mode P)
    scores retrieval and latency from it, the same way it scores the app's
    searches. It holds course text, so it is never committed."""
    path = os.environ.get("SM_QUERY_LOG")
    if not path:
        return
    entry = {
        "course_id": course_id,
        "query": query,
        "sources": [r["source"] for r in results],
        "texts": [r["text"] for r in results],
        "seconds": round(seconds, 3),
    }
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


class Searcher:
    """One retriever per course, built on first use: loading the index opens
    the embedding model and the reranker, which is the slow part."""

    def __init__(self, home: Path, make_retriever=None, today_fn: Callable[[], datetime.date] = today):
        self._home = home
        self._make = make_retriever or _retriever_factory(home)
        self._today = today_fn
        self._retrievers: dict[int, object] = {}

    def search(self, course_id: int, query: str, k: int = DEFAULT_K) -> dict:
        import chat
        import generation

        k = max(1, min(int(k), MAX_K))
        if not indexing.index_exists(self._home / "index.lancedb", _table(course_id)):
            return {
                "course_id": course_id,
                "results": [],
                "note": (
                    f"Course {course_id} is not indexed on this machine yet, so nothing can be searched. "
                    "This is not the same as the material not covering it."
                ),
            }
        start = time.perf_counter()
        if course_id not in self._retrievers:
            self._retrievers[course_id] = self._make(course_id)
        expanded = chat.expand_relative_dates(query, self._today())
        nodes = list(self._retrievers[course_id].retrieve(expanded))[:k]
        results = []
        for n, node_with_score in enumerate(nodes, start=1):
            node = node_with_score.node
            results.append(
                {
                    "n": n,
                    "source": generation.build_citations([node_with_score])[0]["label"],
                    "text": node.get_content()[: chat.SNIPPET_CHARS],
                }
            )
        seconds = time.perf_counter() - start
        logger.info("search course=%s query=%r results=%d seconds=%.2f", course_id, query, len(results), seconds)
        _log_query(course_id, query, results, seconds)
        out = {"course_id": course_id, "query": expanded, "results": results}
        if not results:
            out["note"] = chat.NO_RESULTS
        return out


def build_server(home: Path | None = None, searcher: Searcher | None = None, names_for=canvas_course_names) -> MCPServer:
    home = home or sm_home()
    canvas.SM_HOME = home  # canvas.py reads the Canvas base URL from SM_HOME/config.json
    searcher = searcher or Searcher(home)
    server = MCPServer("second-mind", instructions=INSTRUCTIONS)

    # Tools return dicts, not JSON strings: a str result reaches Claude
    # wrapped as {"result": "<escaped JSON>"}, seen in the first live run.
    @server.tool()
    def list_courses() -> dict:
        """List the student's courses indexed on this machine: course_id, name, last sync time."""
        return list_courses_result(home, names_for)

    @server.tool()
    def search_course_material(course_id: int, query: str, k: int = DEFAULT_K) -> dict:
        """Search one course's materials. Returns up to k chunks, each with a source label to cite."""
        return searcher.search(course_id, query, k)

    return server


def main() -> None:
    logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    build_server().run("stdio")


if __name__ == "__main__":
    main()
