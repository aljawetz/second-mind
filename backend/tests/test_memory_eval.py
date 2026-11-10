"""Memory evaluation harness (scripts/memory_eval.py): the parts that need
no model or dataset. Sampling, what each compared system gets to see, the
benchmark's judge prompts, and the accuracy summary."""

import importlib.util
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "memory_eval.py"


@pytest.fixture(scope="module")
def ev():
    spec = importlib.util.spec_from_file_location("memory_eval", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["memory_eval"] = module
    spec.loader.exec_module(module)
    return module


def _question(qid, qtype, sessions=None, dates=None):
    sessions = sessions or [[{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"}]]
    return {
        "question_id": qid,
        "question_type": qtype,
        "question": "q?",
        "answer": "a",
        "question_date": "2023/04/10 (Mon) 23:07",
        "haystack_sessions": sessions,
        "haystack_dates": dates or ["2023/04/10 (Mon) 17:50"] * len(sessions),
        "haystack_session_ids": [f"s{i}" for i in range(len(sessions))],
        "answer_session_ids": ["s0"],
    }


def test_dates_are_read_as_utc(ev):
    assert ev.parse_date("2023/04/10 (Mon) 23:07") == datetime(2023, 4, 10, 23, 7, tzinfo=timezone.utc)


def test_abstention_questions_are_told_by_their_id(ev):
    assert ev.is_abstention({"question_id": "gpt4_123_abs"})
    assert not ev.is_abstention({"question_id": "gpt4_123"})


def test_sessions_come_back_oldest_first(ev):
    q = _question(
        "q1", "multi-session",
        sessions=[[{"role": "user", "content": "later"}], [{"role": "user", "content": "earlier"}]],
        dates=["2023/04/10 (Mon) 17:50", "2023/04/09 (Sun) 08:00"],
    )
    assert [s.turns[0]["content"] for s in ev.sessions_in_order(q)] == ["earlier", "later"]
    assert ev.sessions_in_order(q)[0].session_id == "s1"


def test_dev_sample_takes_the_same_few_of_each_type_every_time(ev):
    questions = [_question(f"{t}-{i}", t) for t in ("multi-session", "knowledge-update") for i in range(10)]
    sample = ev.sample_questions(questions, per_type=3, seed=7)
    assert sorted(q["question_type"] for q in sample) == ["knowledge-update"] * 3 + ["multi-session"] * 3
    assert [q["question_id"] for q in sample] == [q["question_id"] for q in ev.sample_questions(questions, per_type=3, seed=7)]


def test_sample_leaves_out_excluded_questions(ev):
    questions = [_question(f"m-{i}", "multi-session") for i in range(4)]
    sample = ev.sample_questions(questions, per_type=4, seed=1, exclude={"m-0", "m-1"})
    assert sorted(q["question_id"] for q in sample) == ["m-2", "m-3"]


def test_shipped_chat_baseline_sees_only_the_last_six_pairs_with_answers_cut(ev):
    turns = []
    for i in range(8):
        turns += [{"role": "user", "content": f"u{i}"}, {"role": "assistant", "content": "x" * 2000}]
    context = ev.context_s0(ev.sessions_in_order(_question("q", "multi-session", sessions=[turns])))
    assert "u1" not in context and "u2" in context and "u7" in context
    assert "x" * 1500 in context and "x" * 1501 not in context


def test_full_history_baseline_sees_every_session_with_its_date(ev):
    q = _question(
        "q", "multi-session",
        sessions=[[{"role": "user", "content": "first chat"}], [{"role": "user", "content": "second chat"}]],
        dates=["2023/04/09 (Sun) 08:00", "2023/04/10 (Mon) 17:50"],
    )
    context = ev.context_s1(ev.sessions_in_order(q))
    assert context.index("2023-04-09") < context.index("first chat") < context.index("2023-04-10") < context.index("second chat")


def test_raw_turn_search_returns_the_closest_pairs_and_their_sessions(ev):
    def embed(text):
        return [1.0, 0.0] if "cat" in text else [0.0, 1.0]

    q = _question(
        "q", "multi-session",
        sessions=[
            [{"role": "user", "content": "my cat is Tom"}, {"role": "assistant", "content": "nice"}],
            [{"role": "user", "content": "I like tea"}, {"role": "assistant", "content": "ok"}],
        ],
    )
    context, session_ids = ev.context_s2(ev.sessions_in_order(q), "what is my cat called?", embed, k=1)
    assert "my cat is Tom" in context and "tea" not in context
    assert session_ids == ["s0"]


def test_judge_prompt_follows_the_question_type(ev):
    assert "off-by-one" in ev.judge_prompt("temporal-reasoning", "q", "a", "r")
    assert "updated answer" in ev.judge_prompt("knowledge-update", "q", "a", "r")
    assert "Rubric" in ev.judge_prompt("single-session-preference", "q", "a", "r")
    assert "unanswerable" in ev.judge_prompt("multi-session", "q", "a", "r", abstention=True)
    with pytest.raises(ValueError):
        ev.judge_prompt("made-up-type", "q", "a", "r")


@pytest.mark.parametrize("reply,correct", [("yes", True), ("Yes.", True), ("no", False), ("No, it does not.", False), ("", False)])
def test_a_judge_reply_counts_as_correct_only_when_it_says_yes(ev, reply, correct):
    assert ev.judged_correct(reply) is correct


def test_wilson_interval_brackets_the_rate_and_stays_in_range(ev):
    low, high = ev.wilson(8, 10)
    assert 0 <= low < 0.8 < high <= 1
    assert ev.wilson(0, 0) == (0.0, 0.0)


def test_summary_reports_answerable_and_abstention_apart(ev):
    rows = [
        {"system": "S3", "question_type": "multi-session", "abstention": False, "correct": True, "prompt_tokens": 100, "seconds": 1.0},
        {"system": "S3", "question_type": "multi-session", "abstention": False, "correct": False, "prompt_tokens": 300, "seconds": 3.0},
        {"system": "S3", "question_type": "multi-session", "abstention": True, "correct": True, "prompt_tokens": 100, "seconds": 1.0},
        {"system": "S0", "question_type": "multi-session", "abstention": False, "correct": False, "prompt_tokens": 50, "seconds": 0.5},
    ]
    summary = ev.summarize(rows)
    assert summary["S3"]["answerable"] == {"correct": 1, "n": 2}
    assert summary["S3"]["abstention"] == {"correct": 1, "n": 1}
    assert summary["S3"]["by_type"]["multi-session"] == {"correct": 1, "n": 2}
    assert summary["S3"]["mean_prompt_tokens"] == pytest.approx(500 / 3)
    assert summary["S0"]["answerable"] == {"correct": 0, "n": 1}
