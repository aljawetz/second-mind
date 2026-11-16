"""MCP server for the Claude Code plugin (mcp_server.py, plan M0).

In-process tests go through mcp's Client against the real server object, so
they check MCP responses, not just the Python functions. One test runs the
server as a subprocess over stdio, the way Claude Code starts it, and fails
on anything that is not protocol on stdout.
"""

import datetime
import json
import logging
import os
import re
import sys
from pathlib import Path

import anyio
import numpy as np
import pytest
from llama_index.core import StorageContext, VectorStoreIndex
from llama_index.core.embeddings import BaseEmbedding
from llama_index.core.schema import TextNode
from llama_index.vector_stores.lancedb import LanceDBVectorStore
from mcp import Client, StdioServerParameters

import indexing
import mcp_server
import sync
from embeddings import EMBEDDING_DIM

BACKEND = Path(__file__).resolve().parent.parent
COURSE = 55016


class _HashEmbedding(BaseEmbedding):
    """Bag of words hashed into the real width: offline and deterministic.
    Scores stay under the 0.5 cutoff, so the keyword (BM25) hit is what comes
    back, through the real HybridRetriever."""

    def _embed(self, text: str) -> list[float]:
        vec = np.zeros(EMBEDDING_DIM, dtype=np.float64)
        for token in re.findall(r"[a-z0-9]+", text.lower()) or ["empty"]:
            slot = 0
            for char in token:
                slot = (slot * 33 + ord(char)) % EMBEDDING_DIM
            vec[slot] += 1.0
        return (vec / np.linalg.norm(vec)).tolist()

    def _get_query_embedding(self, query):
        return self._embed(query)

    def _get_text_embedding(self, text):
        return self._embed(text)

    async def _aget_query_embedding(self, query):
        return self._embed(query)

    async def _aget_text_embedding(self, text):
        return self._embed(text)


_PAGES = [
    ("The final exam is worth 20 percent of the grade.", "syllabus", 2),
    ("Project teams may include at most five students.", "01 CourseInfoF26.pdf", 28),
    ("Late work loses ten percent per day.", "syllabus", 9),
]


def _build_index(home: Path, course_id: int = COURSE, pages=_PAGES) -> VectorStoreIndex:
    nodes = [
        TextNode(text=text, metadata={"source": source, "item_type": "file", "page": page, "slide": None, "timestamp": None})
        for text, source, page in pages
    ]
    store = LanceDBVectorStore(uri=str(home / "index.lancedb"), table_name=f"course_{course_id}")
    index = VectorStoreIndex(
        nodes,
        storage_context=StorageContext.from_defaults(vector_store=store),
        embed_model=_HashEmbedding(),
        transformations=[],
    )
    indexing.ensure_fts_index(store.table)
    return index


def _searcher(home: Path, index: VectorStoreIndex, today=datetime.date(2026, 10, 21)):
    calls = []

    def make(course_id):
        calls.append(course_id)
        return mcp_server.make_retriever(index)

    return mcp_server.Searcher(home, make_retriever=make, today_fn=lambda: today), calls


def _call(server, name: str, arguments: dict | None = None) -> dict:
    async def go():
        async with Client(server) as client:
            result = await client.call_tool(name, arguments or {})
            assert not result.is_error, result
            return json.loads(result.content[0].text)

    return anyio.run(go)


def test_tools_and_instructions_are_listed():
    async def go():
        async with Client(mcp_server.build_server(Path("/nonexistent"), names_for=dict)) as client:
            tools = {t.name for t in (await client.list_tools()).tools}
            return tools, client.instructions

    tools, instructions = anyio.run(go)
    assert tools == {"list_courses", "search_course_material", "list_assignments"}
    assert "search_course_material before answering" in instructions


def test_search_returns_chunks_with_citation_labels(tmp_path):
    index = _build_index(tmp_path)
    searcher, _ = _searcher(tmp_path, index)
    server = mcp_server.build_server(tmp_path, searcher=searcher, names_for=dict)

    out = _call(server, "search_course_material", {"course_id": COURSE, "query": "late work penalty"})

    assert out["course_id"] == COURSE
    top = out["results"][0]
    assert {k: top[k] for k in ("n", "source", "text")} == {"n": 1, "source": "syllabus · p.9", "text": "Late work loses ten percent per day."}
    assert [r["n"] for r in out["results"]] == list(range(1, len(out["results"]) + 1))


def test_search_caps_k_and_builds_the_retriever_once(tmp_path):
    index = _build_index(tmp_path)
    searcher, calls = _searcher(tmp_path, index)

    first = searcher.search(COURSE, "percent", k=1)
    searcher.search(COURSE, "percent", k=50)

    assert len(first["results"]) == 1
    assert calls == [COURSE]


def test_the_plugin_searches_without_the_reranker(tmp_path):
    # Measured on heldout: same hit@5 without it, about 0.2 s faster, and one
    # less model for the student to download.
    retriever = mcp_server.make_retriever(_build_index(tmp_path))

    assert retriever._reranker is None


def test_search_returns_more_than_five_when_k_asks(tmp_path):
    # Eight chunks share "rubric", so FTS alone finds them all.
    pages = [(f"The rubric for lab {i} counts style and tests.", "rubric.pdf", i) for i in range(1, 9)]
    index = _build_index(tmp_path, pages=pages)
    searcher, _ = _searcher(tmp_path, index)

    assert len(searcher.search(COURSE, "rubric", k=7)["results"]) == 7
    assert len(searcher.search(COURSE, "rubric")["results"]) == mcp_server.DEFAULT_K


def test_search_expands_relative_dates_with_the_pinned_day(tmp_path):
    index = _build_index(tmp_path)
    searcher, _ = _searcher(tmp_path, index, today=datetime.date(2026, 10, 21))

    out = searcher.search(COURSE, "what is due tomorrow")

    assert out["query"] == "what is due tomorrow Oct 22 2026"


def test_query_log_records_each_search_when_set(tmp_path, monkeypatch):
    index = _build_index(tmp_path)
    searcher, _ = _searcher(tmp_path, index)
    log = tmp_path / "queries.jsonl"

    searcher.search(COURSE, "late work")  # not logged: SM_QUERY_LOG unset
    monkeypatch.setenv("SM_QUERY_LOG", str(log))
    searcher.search(COURSE, "late work penalty")
    searcher.search(COURSE, "team size")

    entries = [json.loads(line) for line in log.read_text().splitlines()]
    assert [e["query"] for e in entries] == ["late work penalty", "team size"]
    assert entries[0]["sources"][0] == "syllabus · p.9"
    assert entries[0]["texts"][0] == "Late work loses ten percent per day."
    assert all(e["course_id"] == COURSE and e["seconds"] >= 0 for e in entries)


def test_search_on_a_course_with_no_index_says_so(tmp_path):
    searcher = mcp_server.Searcher(tmp_path, make_retriever=lambda cid: pytest.fail("must not open an index"))

    out = searcher.search(999, "anything")

    assert out["results"] == []
    assert "not indexed on this machine" in out["note"]


def test_query_log_records_a_search_on_a_course_with_no_index(tmp_path, monkeypatch):
    log = tmp_path / "queries.jsonl"
    monkeypatch.setenv("SM_QUERY_LOG", str(log))
    searcher = mcp_server.Searcher(tmp_path, make_retriever=lambda cid: pytest.fail("must not open an index"))

    searcher.search(999, "anything")

    entries = [json.loads(line) for line in log.read_text().splitlines()]
    assert entries == [{"course_id": 999, "query": "anything", "sources": [], "texts": [], "seconds": 0.0}]


def test_search_with_no_match_returns_the_no_results_note(tmp_path):
    index = _build_index(tmp_path)
    searcher, _ = _searcher(tmp_path, index)

    out = searcher.search(COURSE, "zzzz qqqq")

    assert out["results"] == []
    assert out["note"] == "No matching course material found for this search."


def test_list_courses_reports_indexed_courses_names_and_last_sync(tmp_path):
    _build_index(tmp_path, COURSE)
    _build_index(tmp_path, 56350)
    (tmp_path / "courses" / str(COURSE)).mkdir(parents=True)
    conn = sync.open_manifest(tmp_path / "courses" / str(COURSE) / "manifest.db")
    sync.mark_synced(conn, "file:1", "file", "a.pdf", "2026-10-01T00:00:00Z", "h1")
    conn.close()

    out = _call(mcp_server.build_server(tmp_path, names_for=lambda: {COURSE: "Requirements"}), "list_courses")

    by_id = {c["course_id"]: c for c in out["courses"]}
    assert set(by_id) == {COURSE, 56350}
    assert by_id[COURSE]["name"] == "Requirements"
    assert by_id[COURSE]["last_synced_at"] is not None
    assert by_id[56350] == {"course_id": 56350, "name": None, "last_synced_at": None}


def test_list_courses_skips_canvas_when_nothing_is_indexed(tmp_path):
    out = mcp_server.list_courses_result(tmp_path, names_for=lambda: pytest.fail("no courses, no Canvas call"))

    assert out == {"courses": []}


def test_canvas_failure_lists_courses_without_names(monkeypatch):
    def boom():
        raise RuntimeError("no token")

    monkeypatch.setattr(mcp_server.canvas, "list_courses", boom)

    assert mcp_server.canvas_course_names() == {}


def test_stdio_subprocess_speaks_only_protocol_on_stdout(tmp_path, caplog):
    """Claude Code's view: launch the server, call both tools. mcp's stdio
    client logs every stdout line that is not JSON-RPC ("Failed to parse
    JSONRPC message") and skips it, so a stray print shows up in that log.
    No index here, so no model is loaded and no Canvas call is made."""
    params = StdioServerParameters(
        command=sys.executable,
        args=[str(BACKEND / "mcp_server.py")],
        env={**os.environ, "SM_HOME": str(tmp_path)},
        cwd=str(BACKEND),
    )

    async def go():
        async with Client(params) as client:
            courses = await client.call_tool("list_courses", {})
            missing = await client.call_tool("search_course_material", {"course_id": 1, "query": "x"})
            return json.loads(courses.content[0].text), json.loads(missing.content[0].text)

    with caplog.at_level(logging.ERROR, logger="mcp.client.stdio"):
        courses, missing = anyio.run(go)
    assert [r.getMessage() for r in caplog.records if r.name == "mcp.client.stdio"] == []
    assert courses == {"courses": []}
    assert "not indexed" in missing["note"]


def test_course_names_are_read_from_canvas_until_one_read_succeeds(tmp_path):
    _build_index(tmp_path, COURSE)
    replies = iter([{}, {COURSE: "Requirements"}, {COURSE: "renamed"}])
    calls = []

    def names():
        calls.append(1)
        return next(replies)

    server = mcp_server.build_server(tmp_path, names_for=names)
    first, second, third = (_call(server, "list_courses")["courses"][0]["name"] for _ in range(3))

    assert (first, second, third) == (None, "Requirements", "Requirements")
    assert len(calls) == 2


# --- list_assignments --------------------------------------------------------

import httpx  # noqa: E402

import canvas  # noqa: E402

FUTURE = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
RAW_ASSIGNMENTS = [
    {"id": 11, "name": "Lab 3", "due_at": FUTURE, "points_possible": 50, "html_url": "https://c/a/11",
     "description": "<p>Write tests.</p>", "submission": {"workflow_state": "unsubmitted"},
     "rubric": [{"description": "Coverage", "points": 50, "ratings": []}], "use_rubric_for_grading": True},
]


from zoneinfo import ZoneInfo  # noqa: E402

LA = ZoneInfo("America/Los_Angeles")


def _assignments_server(tmp_path, fetch, zone=lambda: LA):
    return mcp_server.build_server(tmp_path, names_for=dict, assignments_for=fetch, zone_for=zone)


def test_list_assignments_returns_upcoming_work(tmp_path):
    out = _call(_assignments_server(tmp_path, lambda cid: RAW_ASSIGNMENTS), "list_assignments", {"course_id": COURSE})

    assert [a["name"] for a in out["assignments"]] == ["Lab 3"]
    assert out["days"] == 14


def test_list_assignments_with_an_id_returns_the_rubric(tmp_path):
    out = _call(_assignments_server(tmp_path, lambda cid: RAW_ASSIGNMENTS), "list_assignments",
                {"course_id": COURSE, "assignment_id": 11})

    assert out["name"] == "Lab 3"
    assert out["rubric"]["criteria"][0]["criterion"] == "Coverage"
    assert out["description"] == "Write tests."


def test_list_assignments_with_an_unknown_id_says_so(tmp_path):
    out = _call(_assignments_server(tmp_path, lambda cid: RAW_ASSIGNMENTS), "list_assignments",
                {"course_id": COURSE, "assignment_id": 999})

    assert "No assignment 999" in out["note"]


def _index_with_an_assignment(home):
    store = LanceDBVectorStore(uri=str(home / "index.lancedb"), table_name=f"course_{COURSE}")
    node = TextNode(
        text="Due date and points\nDue Fri, Nov 20, 2026 at 11:59 PM EST. Worth 50 points.",
        metadata={"source": "Lab 3", "item_type": "assignment", "page": None, "slide": None, "timestamp": None},
    )
    node.relationships = {}
    VectorStoreIndex([node], storage_context=StorageContext.from_defaults(vector_store=store),
                     embed_model=_HashEmbedding(), transformations=[])


@pytest.mark.parametrize(
    "error, reason",
    [
        (canvas.CanvasError("no Canvas token stored"), "No Canvas token is set up"),
        (httpx.ConnectError("offline"), "Canvas could not be reached"),
        (httpx.HTTPStatusError("401", request=httpx.Request("GET", "https://c"), response=httpx.Response(401)),
         "Your Canvas token no longer works"),
    ],
)
def test_list_assignments_falls_back_to_the_index(tmp_path, error, reason):
    _index_with_an_assignment(tmp_path)

    def fail(cid):
        raise error

    out = _call(_assignments_server(tmp_path, fail), "list_assignments", {"course_id": COURSE})

    assert out["stale"] is True
    assert out["note"].startswith(reason)
    assert out["assignments"] == [{"name": "Lab 3", "schedule": "Due Fri, Nov 20, 2026 at 11:59 PM EST. Worth 50 points."}]


def test_list_assignments_shows_times_in_the_students_zone(tmp_path):
    out = _call(_assignments_server(tmp_path, lambda cid: RAW_ASSIGNMENTS), "list_assignments", {"course_id": COURSE})

    assert out["timezone"] == "America/Los_Angeles"
    row = out["assignments"][0]
    assert row["due_at_display"].endswith(("PST", "PDT"))
    assert row["due_in"].startswith("in ")


def test_zone_comes_from_the_canvas_profile_once(monkeypatch):
    calls = []

    def profile():
        calls.append(1)
        return {"time_zone": "America/Denver"}

    monkeypatch.setattr(mcp_server.canvas, "get_profile", profile)
    zone = mcp_server.canvas_zone()

    assert zone() == ZoneInfo("America/Denver")
    assert zone() == ZoneInfo("America/Denver")
    assert len(calls) == 1


def test_zone_falls_back_to_the_machine_when_canvas_fails(monkeypatch):
    def boom():
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(mcp_server.canvas, "get_profile", boom)

    assert mcp_server.canvas_zone()() == mcp_server.assignments.machine_zone()


def test_search_results_link_to_their_canvas_page(tmp_path):
    (tmp_path / "config.json").write_text('{"canvas_base_url": "https://canvas.example.edu"}')
    store = LanceDBVectorStore(uri=str(tmp_path / "index.lancedb"), table_name=f"course_{COURSE}")
    node = TextNode(text="Late work loses ten percent per day.",
                    metadata={"source": "syllabus", "item_type": "syllabus", "page": None, "slide": None, "timestamp": None})
    node = indexing._with_ref_doc(node, f"syllabus:{COURSE}")
    index = VectorStoreIndex([node], storage_context=StorageContext.from_defaults(vector_store=store),
                             embed_model=_HashEmbedding(), transformations=[])
    indexing.ensure_fts_index(store.table)
    searcher, _ = _searcher(tmp_path, index)

    out = searcher.search(COURSE, "late work")

    assert out["results"][0]["url"] == f"https://canvas.example.edu/courses/{COURSE}/assignments/syllabus"
