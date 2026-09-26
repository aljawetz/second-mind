"""memory/extract.py — turning chat turns into candidate memories (design
spec §5.2, §6). A scripted model stands in for the LLM: these tests check
what the code does with a reply, not whether a real model would give it.
Whether it does is the evaluation's job."""

from datetime import datetime, timezone

import pytest

from memory import extract

AT = datetime(2026, 9, 21, 18, 0, tzinfo=timezone.utc)  # a Monday
TURN = [
    {"role": "user", "content": "I'm on team 4 with Priya."},
    {"role": "assistant", "content": "Great! Team projects are covered in the syllabus [1]."},
]


class ScriptedLLM:
    def __init__(self, *replies):
        self._replies = list(replies)
        self.calls = []

    def complete_json(self, messages):
        self.calls.append(messages)
        return self._replies.pop(0)


def _mem(text="The student is on team 4 with Priya.", kind="fact", **kw):
    return {
        "kind": kind,
        "text": text,
        "importance": 4,
        "event_time": "2026-09-21",
        "entities": ["team 4", "priya"],
        "task_ref_hint": None,
        **kw,
    }


def _extract(memories, messages=TURN, summary="", reply_summary="Talked about teams."):
    llm = ScriptedLLM({"memories": memories, "summary": reply_summary})
    return extract.extract(messages, at=AT, summary=summary, llm=llm), llm


def test_turns_become_candidate_memories_and_an_updated_summary():
    result, _ = _extract([_mem(task_ref_hint="Assignment 3")])

    [m] = result.memories
    assert (m.kind, m.text, m.importance) == ("fact", "The student is on team 4 with Priya.", 4)
    assert m.event_time == datetime(2026, 9, 21, tzinfo=timezone.utc)
    assert m.entities == ["team 4", "priya"]
    assert m.task_ref_hint == "Assignment 3"
    assert result.summary == "Talked about teams."
    assert result.dropped == []


def test_the_model_sees_the_date_the_summary_and_the_turn_without_citation_marks():
    _, llm = _extract([], summary="Earlier: asked about stubs.")

    sent = "\n".join(m["content"] for m in llm.calls[0])
    assert "2026-09-21" in sent and "Monday" in sent  # so "last Tuesday" can become a date
    assert "Earlier: asked about stubs." in sent
    assert "I'm on team 4 with Priya." in sent
    # Citation numbers point at search results the extractor never sees.
    assert "covered in the syllabus." in sent and "[1]" not in sent


def test_only_facts_events_and_tasks_are_kept():
    # "summary" is a real memory kind, but it comes from compression, not here.
    result, _ = _extract([_mem(kind="opinion", text="a"), _mem(kind="summary", text="b"), _mem(kind="task", text="c")])

    assert [m.kind for m in result.memories] == ["task"]
    assert result.dropped == [("a", "kind"), ("b", "kind")]


def test_importance_is_clamped_to_one_through_five():
    result, _ = _extract(
        [_mem(text="a", importance=9), _mem(text="b", importance=0), _mem(text="c", importance="4"), _mem(text="d", importance="high")]
    )

    assert [m.importance for m in result.memories] == [5, 1, 4, 3]


def test_long_text_is_cut_and_empty_text_dropped():
    result, _ = _extract([_mem(text="x" * 400), _mem(text="   "), _mem(text=None)])

    assert [len(m.text) for m in result.memories] == [300]
    assert result.dropped == [("", "empty"), ("", "empty")]


def test_at_most_five_memories_per_student_turn():
    seven = [_mem(text=f"The student likes topic {i}.") for i in range(7)]

    result, _ = _extract(seven)
    assert len(result.memories) == 5
    assert [reason for _, reason in result.dropped] == ["limit", "limit"]

    two_turns = TURN + [{"role": "user", "content": "Also, I prefer Java."}, {"role": "assistant", "content": "Noted."}]
    result, _ = _extract(seven, messages=two_turns)
    assert len(result.memories) == 7


def test_the_same_memory_twice_in_one_reply_is_kept_once():
    result, _ = _extract([_mem(), _mem(text="  the student is on team 4 with Priya. ")])

    assert len(result.memories) == 1
    assert [reason for _, reason in result.dropped] == ["duplicate"]


def test_entities_are_kept_only_as_non_empty_strings():
    result, _ = _extract([_mem(text="a", entities="team 4"), _mem(text="b", entities=["ok", 5, None, "  "])])

    assert [m.entities for m in result.memories] == [[], ["ok"]]


@pytest.mark.parametrize(
    "text",
    [
        "The student got a 72 on the midterm.",
        "The student received a B+ on the quiz.",
        "The student's GPA is 3.8.",
        "The student lost 10 points on Assignment 2.",
        "The student scored 18/20 on Lab 1.",
        "The student was graded harshly on the essay.",
        "Assignment 3 is due Friday.",
        "The student's deadline for the project is December 5.",
    ],
)
def test_grades_scores_and_deadlines_are_never_kept(text):
    # Design spec §5.2: grades and deadlines are never indexed. Cautious on
    # purpose; the evaluation counts what this drops wrongly.
    result, _ = _extract([_mem(text=text)])

    assert result.memories == []
    assert result.dropped == [(text, "grades_or_deadlines")]


@pytest.mark.parametrize(
    "text",
    [
        "The student is on team 4 with Priya.",
        "The student finished part 1 of Assignment 3.",
        "The student got stuck mocking the email service in A3.",
        "The student got a B-tree question wrong in the quiz.",
        "The student missed Class #5.",
        "The student wants examples in Java 21.",
    ],
)
def test_ordinary_memories_get_past_the_grades_filter(text):
    result, _ = _extract([_mem(text=text)])

    assert [m.text for m in result.memories] == [text]


def test_event_time_is_read_from_a_date_or_else_is_when_it_was_said():
    result, _ = _extract(
        [
            _mem(text="a", event_time="2026-09-15"),
            _mem(text="b", event_time="2026-09-15T14:30:00"),
            _mem(text="c", event_time="last week"),
            _mem(text="d", event_time=None),
            _mem(text="e", event_time=20260915),
        ]
    )

    assert [m.event_time for m in result.memories] == [
        datetime(2026, 9, 15, tzinfo=timezone.utc),
        datetime(2026, 9, 15, 14, 30, tzinfo=timezone.utc),
        AT,
        AT,
        AT,
    ]


def test_task_ref_hint_is_a_name_or_nothing():
    result, _ = _extract([_mem(text="a", task_ref_hint="  Assignment 3 "), _mem(text="b", task_ref_hint=3), _mem(text="c", task_ref_hint="")])

    assert [m.task_ref_hint for m in result.memories] == ["Assignment 3", None, None]


@pytest.mark.parametrize(
    "reply",
    [None, "not json at all", [], {}, {"memories": "oops"}, {"memories": [5, "x", None]}, {"summary": 42}],
)
def test_a_malformed_reply_gives_no_memories_and_keeps_the_old_summary(reply):
    # Runs in the background worker: a strange reply must not crash it, and
    # must not wipe out the summary the conversation already has.
    result = extract.extract(TURN, at=AT, summary="Old summary.", llm=ScriptedLLM(reply))

    assert result.memories == []
    assert result.summary == "Old summary."


def test_the_summary_is_kept_to_150_words():
    result, _ = _extract([], reply_summary=" ".join(f"w{i}" for i in range(200)))

    assert result.summary.split() == [f"w{i}" for i in range(150)]
