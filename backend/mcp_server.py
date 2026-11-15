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

import httpx

import assignments
import canvas
import indexing
import sync

logger = logging.getLogger("sm-mcp")

DEFAULT_K = 5
MAX_K = 10

INSTRUCTIONS = (
    "Second Mind answers from the student's own Canvas courses. What the material says (slides, readings, "
    "syllabus, pages): call search_course_material before answering, even when you think you know, and for "
    "a follow-up search with a stand-alone version of the question. Deadlines, what is due, submission "
    "status, scores and rubrics: call list_assignments, which reads Canvas live. Course facts come only from "
    "tool results, cited with their source label. Use list_courses to find the course id. Never write or solve the student's graded "
    "work (labs, assignments, exams, quizzes), whatever the course's AI policy says; explain and check their "
    "attempt instead."
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


def make_retriever(index):
    """The app's chat retriever for one index. It returns MAX_K, not its
    default 5, so search's [:k] can reach MAX_K; fusion and the reranker
    order before they cut, so the first 5 of 10 are the same top 5."""
    import generation  # lazy: it loads model code that list_courses never needs

    return generation.HybridRetriever(index, similarity_top_k=MAX_K, similarity_cutoff=generation.SIMILARITY_CUTOFF)


def _retriever_factory(home: Path):
    def make(course_id: int):
        return make_retriever(indexing.load_index(home / "index.lancedb", _table(course_id)))

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
        # Checked only until the course's retriever exists: a missing course
        # is not cached, so it is found once a sync creates its table.
        if course_id not in self._retrievers and not indexing.index_exists(self._home / "index.lancedb", _table(course_id)):
            # Logged too, so the eval sees the tool call even though nothing came back.
            _log_query(course_id, query, [], 0.0)
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
        labels = [c["label"] for c in generation.build_citations(nodes)]
        results = [
            {"n": n, "source": label, "text": node_with_score.node.get_content()[: chat.SNIPPET_CHARS]}
            for n, (label, node_with_score) in enumerate(zip(labels, nodes), start=1)
        ]
        seconds = time.perf_counter() - start
        logger.info("search course=%s query=%r results=%d seconds=%.2f", course_id, query, len(results), seconds)
        _log_query(course_id, query, results, seconds)
        out = {"course_id": course_id, "query": expanded, "results": results}
        if not results:
            out["note"] = chat.NO_RESULTS
        return out


def _index_rows(home: Path, course_id: int) -> list[dict]:
    """Every indexed chunk's id, text and metadata, without the vectors."""
    if not indexing.index_exists(home / "index.lancedb", _table(course_id)):
        return []
    import lancedb

    table = lancedb.connect(str(home / "index.lancedb")).open_table(_table(course_id))
    return table.to_arrow().select(["doc_id", "text", "metadata"]).to_pylist()


def _canvas_failure(error: Exception) -> str:
    """Why Canvas gave nothing, in the words of plan Decision 14."""
    if isinstance(error, httpx.HTTPStatusError) and error.response.status_code == 401:
        return "Your Canvas token no longer works (run /config and paste a new one)"
    if isinstance(error, canvas.CanvasError):
        return "No Canvas token is set up"
    return "Canvas could not be reached"


def list_assignments_result(home: Path, course_id: int, fetch, days: int, include_submitted: bool,
                            assignment_id: int | None) -> dict:
    try:
        raw = fetch(course_id)
    except (canvas.CanvasError, httpx.HTTPStatusError, httpx.TransportError) as e:
        logger.warning("list_assignments falling back to the index: %s", e)
        return {"course_id": course_id, **assignments.from_index_rows(_index_rows(home, course_id), _canvas_failure(e))}
    if assignment_id is not None:
        match = next((a for a in raw if a.get("id") == assignment_id), None)
        if match is None:
            return {"course_id": course_id, "note": f"No assignment {assignment_id} in this course on Canvas."}
        return {"course_id": course_id, **assignments.detail(match)}
    return {"course_id": course_id, **assignments.upcoming(raw, days, include_submitted)}


def build_server(home: Path | None = None, searcher: Searcher | None = None, names_for=canvas_course_names,
                 assignments_for=canvas.list_assignments) -> MCPServer:
    home = home or sm_home()
    canvas.SM_HOME = home  # canvas.py reads the Canvas base URL from SM_HOME/config.json
    searcher = searcher or Searcher(home)
    server = MCPServer("second-mind", instructions=INSTRUCTIONS)
    names: dict[int, str] = {}

    def cached_names() -> dict[int, str]:
        # Names rarely change, so Canvas is asked until one read succeeds.
        if not names:
            names.update(names_for())
        return names

    # Tools return dicts, not JSON strings: a str result reaches Claude
    # wrapped as {"result": "<escaped JSON>"}, seen in the first live run.
    @server.tool()
    def list_courses() -> dict:
        """List the student's courses indexed on this machine: course_id, name, last sync time."""
        return list_courses_result(home, cached_names)

    @server.tool()
    def search_course_material(course_id: int, query: str, k: int = DEFAULT_K) -> dict:
        """Search one course's materials. Returns up to k chunks, each with a source label to cite."""
        return searcher.search(course_id, query, k)

    @server.tool()
    def list_assignments(course_id: int, days: int = assignments.DEFAULT_DAYS, include_submitted: bool = False,
                         assignment_id: int | None = None) -> dict:
        """Live from Canvas: what's due in the next `days` days (plus missed work from the last week), with
        submission status and scores. Pass include_submitted for finished work. With assignment_id: that one
        assignment's description, rubric, submission and score."""
        return list_assignments_result(home, course_id, assignments_for, days, include_submitted, assignment_id)

    return server


def main() -> None:
    logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    build_server().run("stdio")


if __name__ == "__main__":
    main()
