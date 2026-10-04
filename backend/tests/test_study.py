"""study.py — quizzes and flashcards from a course's indexed material
(implementation-plan.md Step 11, design spec §8, docs/plans/2026-10-03-study-artifacts.md).
A real LanceDB table in a temp dir with made-up vectors, and a scripted model
standing in for the LLM: these tests check what the code does with a reply,
not whether a real model would give it."""

import random

import lancedb
import pytest

import indexing
import study
from embeddings import EMBEDDING_DIM

COURSE = 55710


def _vec(*hot):
    v = [0.0] * EMBEDDING_DIM
    for i in hot:
        v[i] = 1.0
    return v


def _row(n, doc_id, text, source, item_type="file", vector=None, **where):
    meta = {k: None for k in ("page", "slide", "timestamp", "_node_content", "_node_type", "document_id", "doc_id", "ref_doc_id")}
    meta.update({"source": source, "item_type": item_type, **where})
    return {"id": f"n{n}", "doc_id": doc_id, "vector": vector or _vec(0), "text": text, "metadata": meta}


ROWS = [
    _row(1, "file:1", "Stubs return canned answers to calls.", "Lecture 3.pdf", page=1, vector=_vec(1)),
    _row(2, "file:1", "Mocks verify that expected calls happened.", "Lecture 3.pdf", page=2, vector=_vec(2)),
    _row(3, "s-1", "Fakes have working but simplified implementations.", "Class #2", "transcript", timestamp="4:10", vector=_vec(3)),
    _row(4, "page:week-1", "Spies record how they were called.", "Week 1", "page", vector=_vec(4)),
]


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "index.lancedb"
    lancedb.connect(str(path)).create_table(f"course_{COURSE}", data=ROWS, schema=indexing.TABLE_SCHEMA)
    return path


class ScriptedLLM:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = []

    def complete_json(self, messages, **kwargs):
        self.calls.append(messages)
        # Out of script: a model with nothing more to say.
        reply = self.replies.pop(0) if self.replies else {}
        if isinstance(reply, Exception):
            raise reply
        return reply


def _q(question, source="c1", correct=0, hint="Think about what it returns."):
    return {
        "question": question,
        "hint": hint,
        "source": source,
        "options": [
            {"text": f"{question} option {i}", "correct": i == correct, "rationale": f"why {i}"} for i in range(4)
        ],
    }


def _card(front, source="c1"):
    return {"front": front, "back": f"{front} back", "source": source}


# --- material ----------------------------------------------------------------


def test_material_keeps_documents_together_in_reading_order(db):
    chunks = study.material_chunks(db, COURSE)

    assert [c["text"][:5] for c in chunks] == ["Stubs", "Mocks", "Fakes", "Spies"]
    assert [c["citation"]["label"] for c in chunks] == ["Lecture 3.pdf · p.1", "Lecture 3.pdf · p.2", "Class #2 · 4:10", "Week 1"]
    assert chunks[2]["citation"] == {"source_type": "transcript", "label": "Class #2 · 4:10", "item_id": "s-1"}


def test_material_can_be_narrowed_to_chosen_documents(db):
    chunks = study.material_chunks(db, COURSE, item_ids=["s-1", "page:week-1"])

    assert [c["citation"]["item_id"] for c in chunks] == ["s-1", "page:week-1"]


def test_a_course_with_no_index_has_no_material(tmp_path):
    assert study.material_chunks(tmp_path / "index.lancedb", COURSE) == []
    assert study.list_sources(tmp_path / "index.lancedb", COURSE) == []


def test_sources_list_each_document_once(db):
    assert study.list_sources(db, COURSE) == [
        {"item_id": "file:1", "source": "Lecture 3.pdf", "source_type": "file", "chunks": 2, "group": "Course material", "unavailable": None},
        {"item_id": "page:week-1", "source": "Week 1", "source_type": "page", "chunks": 1, "group": "Course material", "unavailable": None},
        {"item_id": "s-1", "source": "Class #2", "source_type": "transcript", "chunks": 1, "group": "Recorded sessions", "unavailable": None},
    ]


# Canvas's own layout (canvas.get_course_structure), shaped like course 56350's:
# weeks are SubHeader items inside one module.
STRUCTURE = [
    {
        "name": "Course Overview",
        "items": [
            {"type": "SubHeader", "title": "Week 01 - Course Overview"},
            {"type": "Page", "title": "Week 1", "page_url": "week-1"},
            {"type": "SubHeader", "title": "Week 02 - Test doubles"},
            {"type": "File", "title": "Lecture 3.pdf", "content_id": 1},
        ],
    },
    {"name": "Deliverables", "items": [{"type": "Assignment", "title": "A1", "content_id": 9}]},
]


def test_sources_are_grouped_and_ordered_by_canvas_weeks(db):
    sources = study.list_sources(db, COURSE, structure=STRUCTURE)

    assert [(s["group"], s["source"]) for s in sources] == [
        ("Week 01 - Course Overview", "Week 1"),
        ("Week 02 - Test doubles", "Lecture 3.pdf"),
        ("Recorded sessions", "Class #2"),  # not in Canvas: after everything that is
    ]


def test_module_files_that_are_not_indexed_are_listed_with_the_reason(db):
    structure = [
        {
            "name": "Course Overview",
            "items": [
                {"type": "SubHeader", "title": "Week 02 - Test doubles"},
                {"type": "File", "title": "Lecture 3.pdf", "content_id": 1},
                {"type": "File", "title": "Lecture 3 recording.mp4", "content_id": 7},
                {"type": "File", "title": "Scanned handout.pdf", "content_id": 8},
                {"type": "File", "title": "README", "content_id": 9},
            ],
        }
    ]

    sources = study.list_sources(db, COURSE, structure=structure)

    rows = [(s["source"], s["group"], s["unavailable"]) for s in sources if s["source_type"] == "file"]
    assert rows == [
        ("Lecture 3.pdf", "Week 02 - Test doubles", None),
        ("Lecture 3 recording.mp4", "Week 02 - Test doubles", "Second Mind can't read .mp4 files"),
        ("Scanned handout.pdf", "Week 02 - Test doubles", "No readable text found, or not synced yet"),
        ("README", "Week 02 - Test doubles", "Second Mind can't read this kind of file"),
    ]
    assert next(s for s in sources if s["source"] == "README")["item_id"] == "file:9"


def test_a_module_without_week_headings_is_its_own_group(tmp_path):
    path = tmp_path / "index.lancedb"
    rows = ROWS + [_row(6, "assignment:9", "Submit a PDF by Friday.", "A1", "assignment")]
    lancedb.connect(str(path)).create_table(f"course_{COURSE}", data=rows, schema=indexing.TABLE_SCHEMA)

    groups = {s["source"]: s["group"] for s in study.list_sources(path, COURSE, structure=STRUCTURE)}

    assert groups["A1"] == "Deliverables"


def test_without_canvas_sources_are_grouped_by_kind(db):
    groups = {s["source"]: s["group"] for s in study.list_sources(db, COURSE)}

    assert groups == {"Lecture 3.pdf": "Course material", "Week 1": "Course material", "Class #2": "Recorded sessions"}


def _chunks(n, size=100):
    return [{"text": "x" * size, "vector": _vec(i % EMBEDDING_DIM), "n": i} for i in range(n)]


def test_material_under_the_budget_is_used_whole():
    chunks = _chunks(5)
    assert study.select_material(chunks, budget_chars=1000) == chunks


def test_over_the_budget_without_a_topic_spreads_across_the_material():
    picked = study.select_material(_chunks(10), budget_chars=500)

    assert [c["n"] for c in picked] == [0, 2, 4, 6, 8]


def test_over_the_budget_with_a_topic_keeps_the_closest_chunks_in_reading_order():
    picked = study.select_material(_chunks(10), budget_chars=300, query_vector=_vec(7, 2, 5))

    assert [c["n"] for c in picked] == [2, 5, 7]


# --- generation --------------------------------------------------------------


def _material(db):
    return study.material_chunks(db, COURSE)


def test_a_quiz_keeps_supported_questions_with_their_citation_and_passage(db):
    llm = ScriptedLLM(
        {"title": "Test doubles", "questions": [_q("What do stubs do?", "c1"), _q("What do mocks check?", "c2")]},
        {"supported": [1, 2]},
    )

    result = study.generate("quiz", _material(db), count=2, difficulty="medium", topic="", llm=llm, rng=random.Random(0))

    assert result["title"] == "Test doubles"
    assert [q["question"] for q in result["items"]] == ["What do stubs do?", "What do mocks check?"]
    first = result["items"][0]
    assert first["citation"]["label"] == "Lecture 3.pdf · p.1"
    assert first["passage"] == "Stubs return canned answers to calls."
    assert first["hint"] == "Think about what it returns."
    assert sum(o["correct"] for o in first["options"]) == 1
    assert {o["text"] for o in first["options"]} == {f"What do stubs do? option {i}" for i in range(4)}
    assert result["stats"] == {"generated": 2, "unsourced": 0, "malformed": 0, "unsupported": 0, "checked": True, "rounds": 1}
    assert result["dropped"] == []


def test_quiz_options_are_shuffled_so_the_answer_is_not_always_first(db):
    questions = [_q(f"Question {i}?", "c1", correct=0) for i in range(12)]
    llm = ScriptedLLM({"title": "T", "questions": questions}, {"supported": list(range(1, 13))})

    result = study.generate("quiz", _material(db), count=12, difficulty="easy", topic="", llm=llm, rng=random.Random(1))

    positions = {next(i for i, o in enumerate(q["options"]) if o["correct"]) for q in result["items"]}
    assert len(positions) > 1


def test_questions_with_a_made_up_source_or_a_broken_shape_are_dropped(db):
    two_correct = _q("Two right answers?", "c1")
    two_correct["options"][1]["correct"] = True
    three_options = _q("Three options?", "c1")
    three_options["options"].pop()
    llm = ScriptedLLM(
        {"title": "T", "questions": [_q("Fine?", "c3"), _q("Invented source?", "c99"), two_correct, three_options, "nonsense"]},
        {"supported": [1]},
    )

    result = study.generate("quiz", _material(db), count=1, difficulty="medium", topic="", llm=llm, rng=random.Random(0))

    assert [q["question"] for q in result["items"]] == ["Fine?"]
    assert result["stats"] == {"generated": 5, "unsourced": 1, "malformed": 3, "unsupported": 0, "checked": True, "rounds": 1}
    assert [(d["reason"], d["question"], d["source"]) for d in result["dropped"]] == [("unsourced", "Invented source?", "c99")]
    # Only the survivors went to the check, numbered from 1, each with its passage.
    check_prompt = llm.calls[1][-1]["content"]
    assert "Fakes have working but simplified implementations." in check_prompt
    assert "Invented source?" not in check_prompt


def test_items_their_passage_does_not_support_are_dropped(db):
    llm = ScriptedLLM(
        {"title": "T", "cards": [_card("Stub", "c1"), _card("Mock", "c2"), _card("Dummy", "c4")]},
        {"supported": [1, 2]},
    )

    result = study.generate("flashcards", _material(db), count=2, difficulty="easy", topic="", llm=llm, rng=random.Random(0))

    assert [c["front"] for c in result["items"]] == ["Stub", "Mock"]
    assert result["items"][1]["citation"]["label"] == "Lecture 3.pdf · p.2"
    assert result["stats"]["unsupported"] == 1
    [dropped] = result["dropped"]
    assert (dropped["reason"], dropped["front"], dropped["passage"]) == ("unsupported", "Dummy", "Spies record how they were called.")


def test_duplicates_are_dropped_and_the_result_is_trimmed_to_the_count(db):
    cards = [
        _card("What are some ethical metrics for AI systems?"),
        _card("What are the ethical metrics for AI systems"),
        _card("What are technical metrics for AI systems?", "c2"),
        _card("Fake", "c3"),
        _card("Spy", "c4"),
    ]
    llm = ScriptedLLM({"title": "T", "cards": cards}, {"supported": [1, 2, 3, 4]})

    result = study.generate("flashcards", _material(db), count=3, difficulty="easy", topic="", llm=llm, rng=random.Random(0))

    assert [c["front"] for c in result["items"]] == [
        "What are some ethical metrics for AI systems?",
        "What are technical metrics for AI systems?",
        "Fake",
    ]
    assert result["stats"]["malformed"] == 1


def test_a_failed_check_keeps_the_items_and_says_they_were_not_checked(db):
    llm = ScriptedLLM({"title": "T", "cards": [_card("Stub")]}, None)

    result = study.generate("flashcards", _material(db), count=1, difficulty="easy", topic="", llm=llm, rng=random.Random(0))

    assert [c["front"] for c in result["items"]] == ["Stub"]
    assert result["stats"]["checked"] is False


def test_the_prompt_carries_the_options_and_the_labelled_material(db):
    llm = ScriptedLLM({"title": "T", "questions": [_q("Q?")]}, {"supported": [1]}, {"questions": []})

    study.generate("quiz", _material(db), count=5, difficulty="hard", topic="mocks vs stubs", llm=llm, rng=random.Random(0))

    prompt = "\n".join(m["content"] for m in llm.calls[0])
    assert "[c3] (4:10) Fakes have working" in prompt
    assert "## Class #2" in prompt
    assert "mocks vs stubs" in prompt
    assert "hard" in prompt.lower()
    assert "8 questions" in prompt  # 5 asked for, plus spares for the ones the check drops


def test_when_the_check_leaves_too_few_a_second_round_asks_for_the_rest(db):
    llm = ScriptedLLM(
        {"title": "Doubles", "cards": [_card("Stub"), _card("Mock", "c2"), _card("Dummy", "c4")]},
        {"supported": [1]},
        {"title": "Ignored", "cards": [_card("stub"), _card("Fake", "c3"), _card("Spy", "c4"), _card("Extra", "c4")]},
        {"supported": [1, 2, 3]},
    )

    result = study.generate("flashcards", _material(db), count=3, difficulty="easy", topic="", llm=llm, rng=random.Random(0))

    assert [c["front"] for c in result["items"]] == ["Stub", "Fake", "Spy"]
    assert result["title"] == "Doubles"
    assert result["stats"] == {"generated": 7, "unsourced": 0, "malformed": 1, "unsupported": 2, "checked": True, "rounds": 2}
    second = llm.calls[2][-1]["content"]
    assert second.startswith("Write 4 flashcards.")  # 2 missing, plus 2 spares
    assert "Already written" in second and "- Stub" in second


def test_a_dropped_item_can_come_back_with_the_right_source(db):
    llm = ScriptedLLM(
        # Round 1: "Stub" cites a passage that doesn't exist, then again with a
        # real one; "Mock" is checked and found unsupported.
        {"title": "T", "cards": [_card("Stub", "c99"), _card("Stub", "c1"), _card("Mock", "c4")]},
        {"supported": [1]},
        # Round 2: "Mock" again, now citing its real passage.
        {"cards": [_card("Mock", "c2")]},
        {"supported": [1]},
    )

    result = study.generate("flashcards", _material(db), count=2, difficulty="easy", topic="", llm=llm, rng=random.Random(0))

    assert [(c["front"], c["citation"]["label"]) for c in result["items"]] == [
        ("Stub", "Lecture 3.pdf · p.1"),
        ("Mock", "Lecture 3.pdf · p.2"),
    ]
    assert result["stats"]["malformed"] == 0


def test_no_second_round_when_the_first_gave_nothing_usable(db):
    llm = ScriptedLLM({"title": "T", "cards": [_card("Invented", "c99")]})

    result = study.generate("flashcards", _material(db), count=3, difficulty="easy", topic="", llm=llm, rng=random.Random(0))

    assert result["items"] == []
    assert len(llm.calls) == 1


def test_syllabus_and_assignments_are_left_out_unless_chosen(tmp_path):
    path = tmp_path / "index.lancedb"
    rows = ROWS + [
        _row(5, "syllabus", "Grading: 40% projects.", "Syllabus", "syllabus"),
        _row(6, "assignment:9", "Submit a PDF by Friday.", "A1", "assignment"),
    ]
    lancedb.connect(str(path)).create_table(f"course_{COURSE}", data=rows, schema=indexing.TABLE_SCHEMA)

    assert {c["citation"]["source_type"] for c in study.material_chunks(path, COURSE)} == {"file", "transcript", "page"}
    assert [c["text"] for c in study.material_chunks(path, COURSE, item_ids=["syllabus"])] == ["Grading: 40% projects."]
    assert len(study.list_sources(path, COURSE)) == 5


def test_a_reply_that_is_not_json_gives_an_empty_result(db):
    llm = ScriptedLLM(None)

    result = study.generate("quiz", _material(db), count=5, difficulty="easy", topic="", llm=llm, rng=random.Random(0))

    assert result["items"] == []
    assert len(llm.calls) == 1  # nothing to check


# --- storage and background runs --------------------------------------------


def _run(tmp_path, db, llm, kind="flashcards", **options):
    options = {"count": "standard", "difficulty": "medium", "topic": "", "item_ids": None, **options}
    summary = study.start(tmp_path, db, COURSE, kind, options, llm=llm, embed=lambda text: _vec(1))
    assert study.wait_idle(10)
    return summary


def test_a_run_saves_the_artifact_and_lists_it(tmp_path, db):
    llm = ScriptedLLM({"title": "Doubles", "cards": [_card("Stub")]}, {"supported": [1]})

    summary = _run(tmp_path, db, llm)

    assert summary["status"] == "generating"
    [listed] = study.list_artifacts(tmp_path, COURSE)
    assert listed["id"] == summary["id"]
    assert (listed["kind"], listed["title"], listed["status"], listed["count"]) == ("flashcards", "Doubles", "done", 1)
    full = study.get_artifact(tmp_path, COURSE, summary["id"])
    assert full["items"][0]["front"] == "Stub"
    assert full["options"]["count"] == "standard"
    assert full["progress"] == {}


def test_a_run_whose_model_call_fails_is_saved_as_an_error(tmp_path, db):
    llm = ScriptedLLM(RuntimeError("no API key stored"))

    summary = _run(tmp_path, db, llm)

    saved = study.get_artifact(tmp_path, COURSE, summary["id"])
    assert saved["status"] == "error"
    assert "no API key stored" in saved["error"]


def test_a_run_with_nothing_usable_is_an_error_not_an_empty_quiz(tmp_path, db):
    llm = ScriptedLLM({"title": "T", "questions": [_q("Invented?", "c99")]}, {"supported": []})

    summary = _run(tmp_path, db, llm, kind="quiz")

    saved = study.get_artifact(tmp_path, COURSE, summary["id"])
    assert saved["status"] == "error"
    assert saved["items"] == []


def test_a_run_left_generating_by_a_restart_reads_as_interrupted(tmp_path, db):
    llm = ScriptedLLM({"title": "T", "cards": [_card("Stub")]}, {"supported": [1]})
    summary = _run(tmp_path, db, llm)
    artifact = study.get_artifact(tmp_path, COURSE, summary["id"])
    study._write(study._path(tmp_path, COURSE, summary["id"]), {**artifact, "status": "generating"})

    assert study.get_artifact(tmp_path, COURSE, summary["id"])["status"] == "error"


def test_count_names_map_to_numbers_and_unknown_options_are_rejected():
    assert study.item_count("quiz", "fewer") < study.item_count("quiz", "standard") < study.item_count("quiz", "more")
    with pytest.raises(ValueError):
        study.check_options("quiz", {"count": "lots", "difficulty": "easy", "topic": "", "item_ids": None})
    with pytest.raises(ValueError):
        study.check_options("essay", {"count": "fewer", "difficulty": "easy", "topic": "", "item_ids": None})
    with pytest.raises(ValueError):
        study.check_options("quiz", {"count": "fewer", "difficulty": "brutal", "topic": "", "item_ids": None})
    assert study.check_options("quiz", {"count": "fewer", "difficulty": "easy"}) == {
        "count": "fewer",
        "difficulty": "easy",
        "topic": "",
        "item_ids": None,
    }


def test_progress_is_saved_and_artifacts_can_be_deleted(tmp_path, db):
    llm = ScriptedLLM({"title": "T", "cards": [_card("Stub")]}, {"supported": [1]})
    summary = _run(tmp_path, db, llm)

    study.save_progress(tmp_path, COURSE, summary["id"], {"position": 0, "marks": {"0": "got"}})
    assert study.get_artifact(tmp_path, COURSE, summary["id"])["progress"] == {"position": 0, "marks": {"0": "got"}}

    study.delete_artifact(tmp_path, COURSE, summary["id"])
    assert study.get_artifact(tmp_path, COURSE, summary["id"]) is None
    assert study.list_artifacts(tmp_path, COURSE) == []
    with pytest.raises(KeyError):
        study.save_progress(tmp_path, COURSE, summary["id"], {})


# --- routes: the real HTTP handler, in-process ------------------------------


@pytest.fixture
def app(tmp_path, monkeypatch):
    import http.client
    import json
    import threading
    from types import SimpleNamespace

    import config
    import llm
    import main

    config.write_config(tmp_path, {"selected_courses": [COURSE]})
    lancedb.connect(str(tmp_path / "index.lancedb")).create_table(f"course_{COURSE}", data=ROWS, schema=indexing.TABLE_SCHEMA)
    monkeypatch.setattr(main, "SM_HOME", tmp_path)
    import canvas

    monkeypatch.setattr(canvas, "get_course_structure", lambda course_id: STRUCTURE)
    model = ScriptedLLM()
    monkeypatch.setattr(llm, "current_provider", lambda *a, **kw: model)
    server = main.ThreadingHTTPServer(("127.0.0.1", 0), main.Handler)
    threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()

    def call(method, path, body=None):
        conn = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=10)
        conn.request(method, path, json.dumps(body) if body is not None else None)
        res = conn.getresponse()
        payload = json.loads(res.read().decode())
        conn.close()
        return res.status, payload

    yield SimpleNamespace(call=call, model=model, home=tmp_path)
    assert study.wait_idle(10)
    server.shutdown()
    server.server_close()


def test_routes_make_a_quiz_then_list_open_save_progress_and_delete_it(app):
    app.model.replies += [{"title": "Doubles", "questions": [_q("What do stubs do?", "c1")]}, {"supported": [1]}]

    status, started = app.call("POST", f"/courses/{COURSE}/study", {"kind": "quiz", "count": "fewer", "difficulty": "easy"})
    assert status == 202
    assert started["status"] == "generating"
    assert study.wait_idle(10)

    status, listed = app.call("GET", f"/courses/{COURSE}/study")
    assert status == 200
    assert [(a["id"], a["status"], a["title"]) for a in listed["artifacts"]] == [(started["id"], "done", "Doubles")]

    status, quiz = app.call("GET", f"/courses/{COURSE}/study/{started['id']}")
    assert status == 200
    assert quiz["items"][0]["citation"]["label"] == "Lecture 3.pdf · p.1"

    status, _ = app.call("POST", f"/courses/{COURSE}/study/{started['id']}/progress", {"progress": {"answers": {"0": 2}}})
    assert status == 200
    assert app.call("GET", f"/courses/{COURSE}/study/{started['id']}")[1]["progress"] == {"answers": {"0": 2}}

    assert app.call("DELETE", f"/courses/{COURSE}/study/{started['id']}")[0] == 200
    assert app.call("GET", f"/courses/{COURSE}/study/{started['id']}")[0] == 404


def test_sources_route_lists_the_indexed_documents(app):
    status, body = app.call("GET", f"/courses/{COURSE}/study/sources")

    assert status == 200
    assert [(s["item_id"], s["group"]) for s in body["sources"]] == [
        ("page:week-1", "Week 01 - Course Overview"),
        ("file:1", "Week 02 - Test doubles"),
        ("s-1", "Recorded sessions"),
    ]


def test_sources_route_still_lists_everything_when_canvas_is_unreachable(app, monkeypatch):
    import canvas
    import httpx

    def offline(course_id):
        raise httpx.ConnectError("no network")

    monkeypatch.setattr(canvas, "get_course_structure", offline)

    status, body = app.call("GET", f"/courses/{COURSE}/study/sources")

    assert status == 200
    assert {s["group"] for s in body["sources"]} == {"Course material", "Recorded sessions"}


def test_bad_options_and_unknown_courses_are_refused(app):
    assert app.call("POST", f"/courses/{COURSE}/study", {"kind": "essay"})[0] == 400
    assert app.call("POST", f"/courses/{COURSE}/study", {"kind": "quiz", "difficulty": "brutal"})[0] == 400
    assert app.call("POST", "/courses/999/study", {"kind": "quiz"})[0] == 404
    assert app.call("GET", "/courses/999/study")[0] == 404
    assert app.call("POST", f"/courses/{COURSE}/study/nope/progress", {"progress": {}})[0] == 404
    assert app.model.calls == []


def test_progress_that_is_not_an_object_is_refused(app):
    app.model.replies += [{"title": "T", "cards": [_card("Stub")]}, {"supported": [1]}]
    _, started = app.call("POST", f"/courses/{COURSE}/study", {"kind": "flashcards"})
    assert study.wait_idle(10)
    path = f"/courses/{COURSE}/study/{started['id']}/progress"

    assert app.call("POST", path, {"progress": [1, 2]})[0] == 400
    assert app.call("POST", path, {"progress": "position 3"})[0] == 400
    assert app.call("POST", path, {})[0] == 200  # missing: saved as {}
    assert app.call("GET", f"/courses/{COURSE}/study/{started['id']}")[1]["progress"] == {}


def test_a_missing_model_key_fails_before_anything_is_saved(app, monkeypatch):
    import llm

    def no_key(*a, **kw):
        raise RuntimeError("no OpenAI API key stored")

    monkeypatch.setattr(llm, "current_provider", no_key)

    status, body = app.call("POST", f"/courses/{COURSE}/study", {"kind": "flashcards"})

    assert status == 401
    assert body["error"]["code"] == "llm_auth_failed"
    assert study.list_artifacts(app.home, COURSE) == []


def test_export_writes_a_csv_without_removed_cards_or_overwriting(tmp_path, db):
    import csv

    llm = ScriptedLLM({"title": "Doubles: part 1/2", "cards": [_card("Stub"), _card("Mock", "c2")]}, {"supported": [1, 2]})
    summary = _run(tmp_path, db, llm)
    study.save_progress(tmp_path, COURSE, summary["id"], {"removed": [1]})
    out = tmp_path / "Downloads"

    first = study.export_csv(tmp_path, COURSE, summary["id"], out)
    second = study.export_csv(tmp_path, COURSE, summary["id"], out)

    assert first.name == "Doubles  part 1 2.csv"
    assert second.name == "Doubles  part 1 2 (2).csv"
    rows = list(csv.reader(first.read_text(encoding="utf-8-sig").splitlines()))
    assert rows == [["Front", "Back", "Source"], ["Stub", "Stub back", "Lecture 3.pdf · p.1"]]


def test_export_route_saves_a_quiz_to_the_downloads_folder(app, monkeypatch):
    import csv

    import main

    monkeypatch.setattr(main, "DOWNLOADS_DIR", app.home / "Downloads")
    app.model.replies += [{"title": "Doubles", "questions": [_q("What do stubs do?", "c1", correct=2)]}, {"supported": [1]}]
    _, started = app.call("POST", f"/courses/{COURSE}/study", {"kind": "quiz"})
    assert study.wait_idle(10)

    status, body = app.call("POST", f"/courses/{COURSE}/study/{started['id']}/export")

    assert status == 200
    from pathlib import Path

    [header, row] = list(csv.reader(Path(body["path"]).read_text(encoding="utf-8-sig").splitlines()))
    assert header == ["Question", "A", "B", "C", "D", "Answer", "Source"]
    assert row[0] == "What do stubs do?"
    assert row[1 + "ABCD".index(row[5])] == "What do stubs do? option 2"
    assert app.call("POST", f"/courses/{COURSE}/study/nope/export")[0] == 404
