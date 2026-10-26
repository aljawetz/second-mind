"""Fact labels and the Sprint 8 held-out question set.

A result is relevant when its text holds the fact that answers the question,
not when its file name matches. No index, no network, no API key.
"""

import importlib.util
import sys
from pathlib import Path

import pytest
from llama_index.core.schema import NodeWithScore, TextNode

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "ask_modes_eval.py"


@pytest.fixture(scope="module")
def eval_mod():
    spec = importlib.util.spec_from_file_location("ask_modes_eval", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["ask_modes_eval"] = module
    spec.loader.exec_module(module)
    return module


def _node(source: str, text: str, page: int = 1) -> NodeWithScore:
    node = TextNode(text=text, metadata={"source": source, "item_type": "file", "page": page})
    return NodeWithScore(node=node, score=0.9)


class _FixedRetriever:
    """Returns the same nodes for every question."""

    def __init__(self, nodes):
        self._nodes = nodes

    def retrieve(self, _query):
        return list(self._nodes)


def _case(case_id, gold_facts=None, gold_source=None, **extra):
    case = {
        "id": case_id,
        "course": 1,
        "kind": "course_fact",
        "turns": ["a question"],
        "gold_source": gold_source,
        "gold_facts": gold_facts,
    }
    case.update(extra)
    return case


def _score(eval_mod, cases, nodes):
    return eval_mod.evaluate_retrieval(
        cases, lambda _course: None, retriever_for=lambda _index: _FixedRetriever(nodes)
    )


# --- the helpers ----------------------------------------------------------


def test_fact_match_ignores_case_and_line_breaks(eval_mod):
    text = "Midterm:\n  Wednesday,   October 7th"
    assert eval_mod.contains_fact(["midterm: wednesday, october 7th"], text)


def test_fact_match_needs_the_whole_fact(eval_mod):
    assert not eval_mod.contains_fact(["Midterm: Wednesday, October 7th"], "Midterm: Wednesday")


def test_any_listed_fact_counts(eval_mod):
    assert eval_mod.contains_fact(["not here", "Due Wed, Oct 7, 2026"], "Due Wed, Oct 7, 2026 at 8 AM")


def test_no_gold_facts_means_no_fact_score(eval_mod):
    assert eval_mod.recall_by_fact(None, ["anything"]) is None
    assert eval_mod.precision_by_fact([], ["anything"]) is None


def test_fact_precision_is_the_share_of_results_that_hold_the_fact(eval_mod):
    texts = ["has the fact", "does not", "has the fact too", "nope"]
    assert eval_mod.precision_by_fact(["the fact"], texts) == 0.5
    assert eval_mod.recall_by_fact(["the fact"], texts) is True


def test_fact_precision_is_none_for_an_empty_search(eval_mod):
    assert eval_mod.precision_by_fact(["the fact"], []) is None
    assert eval_mod.recall_by_fact(["the fact"], []) is False


# --- through evaluate_retrieval ------------------------------------------


def test_file_name_misses_but_the_fact_is_found(eval_mod):
    """The case the plan names: the right chunk comes from a file the answer
    key does not list, so file-name scoring calls it a miss."""
    nodes = [_node("01 CourseInfoF26.pdf", "Midterm: Wednesday, October 7th")]
    case = _case("F1", gold_facts=["Midterm: Wednesday, October 7th"], gold_source="syllabus")

    row = _score(eval_mod, [case], nodes)["results"][0]

    assert row["recall_at_5"] is False
    assert row["recall_by_fact"] is True
    assert row["precision_by_fact"] == 1.0


def test_the_file_name_scores_are_unchanged_by_fact_labels(eval_mod):
    nodes = [_node("syllabus", "Late work loses ten percent per day.")]
    plain = _case("A", gold_source="syllabus")
    labelled = _case("A", gold_source="syllabus", gold_facts=["ten percent per day"])

    plain_row = _score(eval_mod, [plain], nodes)["results"][0]
    labelled_row = _score(eval_mod, [labelled], nodes)["results"][0]

    assert plain_row["recall_at_5"] == labelled_row["recall_at_5"] is True
    assert plain_row["precision_at_5"] == labelled_row["precision_at_5"] == 1.0
    assert plain_row["recall_by_fact"] is None


def test_summary_reports_precision_both_ways(eval_mod):
    hit = _case("HIT", gold_facts=["the fact"])
    empty = _case("EMPTY", gold_facts=["the fact"])
    nodes_by_case = {"HIT": [_node("a.pdf", "the fact")], "EMPTY": []}

    rows = []
    for case in (hit, empty):
        rows += _score(eval_mod, [case], nodes_by_case[case["id"]])["results"]
    facts = eval_mod.retrieval_metrics(rows)["fact_labels"]

    assert facts["n"] == 2
    assert facts["hits"] == 1
    assert facts["recall"] == 0.5
    assert facts["precision_empty_skipped"] == 1.0
    assert facts["precision_empty_as_zero"] == 0.5
    assert facts["n_precision"] == 1


def test_unanswerable_questions_count_the_results_they_got(eval_mod):
    nodes = [_node("a.pdf", "weak match"), _node("b.pdf", "another weak match")]
    gone = _case("U1", kind="not_in_course")

    metrics = _score(eval_mod, [gone], nodes)["metrics"]

    assert metrics["unanswerable"] == {"n": 1, "returned": 2, "with_results": 1}
    assert "fact_labels" not in metrics


def test_no_fact_cases_leaves_the_old_summary_shape(eval_mod):
    nodes = [_node("syllabus", "text")]
    metrics = _score(eval_mod, [_case("A", gold_source="syllabus")], nodes)["metrics"]
    assert "fact_labels" not in metrics
    assert "unanswerable" not in metrics


# --- the Sprint 8 held-out set -------------------------------------------


def test_sprint8_set_is_the_right_size_and_shape(eval_mod):
    cases = eval_mod.cases_for("sprint8")
    answerable = [c for c in cases if c.get("gold_facts")]
    unanswerable = [c for c in cases if c["kind"] == "not_in_course"]

    assert 10 <= len(cases) <= 15
    assert len(answerable) + len(unanswerable) == len(cases)
    assert unanswerable, "the set needs questions the course cannot answer"
    assert all(len(c["turns"]) == 1 for c in cases)
    assert all(c["gold_answer"] for c in cases)


def test_sprint8_ids_and_questions_are_unique(eval_mod):
    cases = eval_mod.cases_for("sprint8")
    ids = [c["id"] for c in cases]
    questions = [c["turns"][0].lower() for c in cases]
    assert len(set(ids)) == len(ids)
    assert len(set(questions)) == len(questions)


def test_sprint8_does_not_reuse_a_sprint7_question_or_id(eval_mod):
    """The set is for checking, never tuning: it must stay apart from the set
    the cutoff was chosen on."""
    sprint7 = eval_mod.cases_for("sprint7")
    seen_questions = {q.lower() for c in sprint7 for q in c["turns"]}
    seen_ids = {c["id"] for c in sprint7}

    for case in eval_mod.cases_for("sprint8"):
        assert case["turns"][0].lower() not in seen_questions
        assert case["id"] not in seen_ids


def test_sprint8_facts_are_real_strings_for_known_courses(eval_mod):
    known = {eval_mod.REQ, eval_mod.AI, eval_mod.TST}
    for case in eval_mod.cases_for("sprint8"):
        assert case["course"] in known
        for fact in case.get("gold_facts") or []:
            assert isinstance(fact, str) and len(fact.strip()) >= 8


def test_midterm_date_questions_accept_the_chunks_that_state_the_date(eval_mod):
    by_id = {c["id"]: c for c in eval_mod.cases_for("sprint7")}
    for case_id in ("F1", "V1"):
        facts = by_id[case_id]["gold_facts"]
        assert "Midterm: Wednesday, October 7th" in facts
        assert "Due Wed, Oct 7, 2026" in facts


# --- ranking quality that truncation cannot inflate -----------------------


def test_first_rank_is_the_position_of_the_first_chunk_with_the_fact(eval_mod):
    texts = ["nothing", "still nothing", "the fact is here", "the fact again"]
    assert eval_mod.first_rank_by_fact(["the fact"], texts) == 3


def test_first_rank_is_none_without_facts_or_without_a_hit(eval_mod):
    assert eval_mod.first_rank_by_fact(None, ["the fact"]) is None
    assert eval_mod.first_rank_by_fact(["the fact"], ["other", "text"]) is None
    assert eval_mod.first_rank_by_fact(["the fact"], []) is None


def test_mrr_and_top1_in_the_summary(eval_mod):
    cases = [_case(name, gold_facts=["the fact"]) for name in ("FIRST", "THIRD", "NONE")]
    nodes_by_case = {
        "FIRST": [_node("a.pdf", "the fact"), _node("b.pdf", "x")],
        "THIRD": [_node("a.pdf", "x"), _node("b.pdf", "y"), _node("c.pdf", "the fact")],
        "NONE": [_node("a.pdf", "x")],
    }
    rows = []
    for case in cases:
        rows += _score(eval_mod, [case], nodes_by_case[case["id"]])["results"]
    facts = eval_mod.retrieval_metrics(rows)["fact_labels"]

    assert facts["top1_hits"] == 1
    assert facts["mrr"] == pytest.approx((1 + 1 / 3 + 0) / 3)


def test_returning_fewer_results_raises_precision_but_not_mrr(eval_mod):
    """Why MRR is reported beside precision: cutting the tail is not better ranking."""
    five = [_node("a.pdf", "the fact")] + [_node(f"{i}.pdf", "filler") for i in range(4)]
    one = five[:1]
    case = _case("A", gold_facts=["the fact"])

    wide = _score(eval_mod, [case], five)["metrics"]["fact_labels"]
    cut = _score(eval_mod, [case], one)["metrics"]["fact_labels"]

    assert cut["precision_empty_skipped"] > wide["precision_empty_skipped"]
    assert cut["mrr"] == wide["mrr"] == 1.0


# --- the Sprint 8 test set -----------------------------------------------


def test_sprint8_test_set_is_apart_from_every_other_set(eval_mod):
    """It is frozen and searched once. A shared question or id would let a
    score from a set we tuned on pass for a score from one we did not."""
    test = eval_mod.cases_for("sprint8-test")
    others = eval_mod.cases_for("sprint7") + eval_mod.cases_for("sprint8")
    other_questions = {q.lower() for c in others for q in c["turns"]}
    other_ids = {c["id"] for c in others}

    assert len({c["id"] for c in test}) == len(test)
    for case in test:
        assert case["turns"][0].lower() not in other_questions
        assert case["id"] not in other_ids


def test_sprint8_test_set_has_conceptual_and_unanswerable_questions(eval_mod):
    test = eval_mod.cases_for("sprint8-test")
    kinds = {c["kind"] for c in test}

    assert len(test) >= 20
    assert {"course_fact", "concept_covered", "not_in_course"} <= kinds
    assert all(len(c["turns"]) == 1 for c in test)
    for case in test:
        if case["kind"] == "not_in_course":
            assert not case.get("gold_facts")
        else:
            assert case["gold_facts"] and all(len(f.strip()) >= 8 for f in case["gold_facts"])


# --- multi-turn scoring ---------------------------------------------------


class _ByQueryRetriever:
    """Returns nodes keyed by the exact query text."""

    def __init__(self, by_query):
        self._by_query = by_query
        self.asked = []

    def retrieve(self, query):
        self.asked.append(query)
        return list(self._by_query.get(query, []))


def _chat(turns):
    from_turns = lambda i: [t[i] for t in turns]  # noqa: E731
    return {
        "id": "CH",
        "course": 1,
        "kind": "follow_up",
        "turns": from_turns(0),
        "rewrites": from_turns(1),
        "turn_facts": from_turns(2),
        "gold_source": None,
    }


def _score_chat(eval_mod, case, by_query):
    retriever = _ByQueryRetriever(by_query)
    report = eval_mod.evaluate_retrieval([case], lambda _c: None, retriever_for=lambda _i: retriever)
    return report, retriever


def test_each_turn_is_scored_against_its_own_facts(eval_mod):
    case = _chat([("first?", None, ["fact one"]), ("second?", None, ["fact two"])])
    by_query = {"first?": [_node("a", "fact one")], "second?": [_node("a", "fact one")]}

    report, _ = _score_chat(eval_mod, case, by_query)
    first, second = report["results"]

    assert first["recall_by_fact"] is True
    assert second["recall_by_fact"] is False


def test_a_rewrite_is_searched_as_its_own_row_and_kept_out_of_the_headline(eval_mod):
    case = _chat([("when is a?", None, ["fact a"]), ("and b?", "when is b?", ["fact b"])])
    by_query = {
        "when is a?": [_node("x", "fact a")],
        "and b?": [],
        "when is b?": [_node("x", "fact b")],
    }

    report, retriever = _score_chat(eval_mod, case, by_query)
    variants = [(r["turn"], r["variant"], r["query"]) for r in report["results"]]

    assert variants == [(1, "as_typed", "when is a?"), (2, "as_typed", "and b?"), (2, "rewritten", "when is b?")]
    assert retriever.asked == ["when is a?", "and b?", "when is b?"]
    assert report["metrics"]["n"] == 2  # the rewritten search is not a third question
    assert report["metrics"]["fact_labels"]["hits"] == 1  # only "when is a?" hit as typed


def test_follow_up_summary_compares_typed_and_rewritten(eval_mod):
    case = _chat([("when is a?", None, ["fact a"]), ("and b?", "when is b?", ["fact b"])])
    by_query = {"when is a?": [_node("x", "fact a")], "and b?": [], "when is b?": [_node("x", "fact b")]}

    metrics = _score_chat(eval_mod, case, by_query)[0]["metrics"]["follow_ups"]

    assert metrics["as_typed"] == {"n": 1, "hits": 0, "top1_hits": 0, "mrr": 0.0}
    assert metrics["rewritten"] == {"n": 1, "hits": 1, "top1_hits": 1, "mrr": 1.0}


def test_a_follow_up_the_course_cannot_answer_counts_as_unanswerable(eval_mod):
    case = _chat([("when is a?", None, ["fact a"]), ("who is the guest?", "who is the guest lecturer?", None)])
    by_query = {"when is a?": [_node("x", "fact a")], "who is the guest?": [_node("x", "weak")]}

    metrics = _score_chat(eval_mod, case, by_query)[0]["metrics"]

    assert metrics["unanswerable"] == {"n": 1, "returned": 1, "with_results": 1}


def test_single_question_cases_still_get_one_row_per_question(eval_mod):
    case = {"id": "A", "course": 1, "kind": "course_fact", "turns": ["q"], "gold_source": None, "gold_facts": ["f"]}
    report, retriever = _score_chat(eval_mod, case, {"q": [_node("x", "f")]})

    assert len(report["results"]) == 1
    assert report["results"][0]["variant"] == "as_typed"
    assert "follow_ups" not in report["metrics"]


# --- the Sprint 8 chat set ------------------------------------------------


def test_chat_set_is_apart_from_the_other_sets(eval_mod):
    chats = eval_mod.cases_for("sprint8-chat")
    others = (
        eval_mod.cases_for("sprint7") + eval_mod.cases_for("sprint8") + eval_mod.cases_for("sprint8-test")
    )
    other_ids = {c["id"] for c in others}
    other_questions = {q.lower() for c in others for q in c["turns"]}

    assert len({c["id"] for c in chats}) == len(chats)
    for case in chats:
        assert case["id"] not in other_ids
        for turn in case["turns"]:
            assert turn.lower() not in other_questions


def test_chat_cases_are_well_formed(eval_mod):
    chats = eval_mod.cases_for("sprint8-chat")
    follow_ups = 0
    for case in chats:
        n = len(case["turns"])
        assert n >= 2
        assert len(case["rewrites"]) == len(case["turn_facts"]) == n
        assert case["rewrites"][0] is None, "the first turn needs no rewrite"
        for turn, rewrite in zip(case["turns"], case["rewrites"]):
            assert rewrite is None or rewrite.lower() != turn.lower()
        follow_ups += sum(r is not None for r in case["rewrites"])
    assert len(chats) >= 10
    assert follow_ups >= 10


def test_chat_set_covers_follow_ups_that_need_no_rewrite_and_unanswerable_ones(eval_mod):
    chats = eval_mod.cases_for("sprint8-chat")
    later_turns = [(c["rewrites"][i], c["turn_facts"][i]) for c in chats for i in range(1, len(c["turns"]))]

    assert any(rewrite is None for rewrite, _ in later_turns), "a topic-shift turn that stands alone"
    assert any(facts is None for _, facts in later_turns), "a follow-up the course cannot answer"


def test_report_prints_rewritten_rows_and_the_follow_up_table(eval_mod, capsys):
    case = _chat([("when is a?", None, ["fact a"]), ("and b?", "when is b?", ["fact b"])])
    by_query = {"when is a?": [_node("x", "fact a")], "and b?": [], "when is b?": [_node("x", "fact b")]}
    scored = _score_chat(eval_mod, case, by_query)[0]

    eval_mod.print_retrieval_report({"set": "sprint8-chat", **scored})
    out = capsys.readouterr().out

    assert "CH.2 (rewritten)" in out
    assert "Follow-up turns: as typed vs a standalone rewrite" in out
    assert "| as typed | 1 | 0/1 |" in out
    assert "| rewritten | 1 | 1/1 |" in out
    assert "upper bound" in out


# --- the chat the student wrote himself -----------------------------------


def test_user_chat_is_apart_from_the_other_sets_and_well_formed(eval_mod):
    user = eval_mod.cases_for("sprint8-user")
    others = (
        eval_mod.cases_for("sprint7") + eval_mod.cases_for("sprint8")
        + eval_mod.cases_for("sprint8-test") + eval_mod.cases_for("sprint8-chat")
    )
    other_ids = {c["id"] for c in others}
    other_questions = {q.lower() for c in others for q in c["turns"]}

    assert len(user) == 1
    case = user[0]
    n = len(case["turns"])
    assert len(case["rewrites"]) == len(case["turn_facts"]) == n
    assert case["id"] not in other_ids
    assert all(q.lower() not in other_questions for q in case["turns"])
    for turn, rewrite in zip(case["turns"], case["rewrites"]):
        assert rewrite is None or rewrite.lower() != turn.lower()


def test_user_chat_marks_the_vague_and_unusable_questions_unanswerable(eval_mod):
    case = eval_mod.cases_for("sprint8-user")[0]
    by_question = dict(zip(case["turns"], case["turn_facts"]))

    assert by_question["what do i need to do?"] is None
    assert by_question["explain the last class"] is None
    assert by_question["what do I need to do for next week?"]


def test_turn_gold_answer_uses_the_turns_own_facts(eval_mod):
    case = {"turn_facts": [["Due Wed, Oct 28"], None]}
    assert "Due Wed, Oct 28" in eval_mod.turn_gold_answer(case, 1)
    assert "not available" in eval_mod.turn_gold_answer(case, 2)
    assert eval_mod.turn_gold_answer({"gold_answer": "x"}, 1) is None


def test_judge_notes_override_the_fragment_fact(eval_mod):
    case = {"turn_facts": [["Assignment 3 (Docker Compose) due"]], "judge_notes": {1: "due Oct 28"}}
    assert eval_mod.turn_gold_answer(case, 1) == "due Oct 28"
    assert all("judge_notes" in c for c in eval_mod.SPRINT8_CHAT_CASES if c["id"] == "CH1")
    assert eval_mod.SPRINT8_USER_CASES[0]["judge_notes"][1]
