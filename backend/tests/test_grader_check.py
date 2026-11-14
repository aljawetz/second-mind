"""scripts/grader_check.py — checking the answer judge against hand grades
(RAG gaps plan, task 6). Pure parts only: picking turns, the grading sheet,
reading grades back, and the agreement numbers. No model calls."""

import importlib.util
import random
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "grader_check.py"


@pytest.fixture(scope="module")
def gc():
    spec = importlib.util.spec_from_file_location("grader_check", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _results(chats=8, turns=3):
    """ask_modes_eval rows for modes E and G, `turns` turns per chat."""
    rows = []
    for c in range(1, chats + 1):
        for t in range(1, turns + 1):
            for mode in ("E", "G"):
                rows.append(
                    {
                        "case": f"N{c}",
                        "course": 55016,
                        "turn": t,
                        "mode": mode,
                        "question": f"question {c}.{t}",
                        "answer": f"{mode} answer {c}.{t}",
                        "sources": [f"Page {c}"] if mode == "E" else [],
                    }
                )
    return rows


def _cases(chats=8, turns=3):
    return [
        {
            "id": f"N{c}",
            "course": 55016,
            "kind": "follow_up",
            "turns": [f"question {c}.{t}" for t in range(1, turns + 1)],
            "turn_facts": [[f"fact {c}.{t}"] for t in range(1, turns + 1)],
            "gold_answer": f"chat {c}",
        }
        for c in range(1, chats + 1)
    ]


# --- picking turns -----------------------------------------------------------


def test_twenty_turns_are_picked_ten_per_half_with_whole_chats_in_one_half(gc):
    items = gc.select_turns(_results(), _cases(), n=20, seed=0)

    assert len(items) == 20
    assert [i["n"] for i in items] == list(range(1, 21))
    halves = {i["half"] for i in items}
    assert halves == {"tune", "report"}
    assert sum(i["half"] == "tune" for i in items) == 10
    # A chat's turns share context, so a chat is never split across halves.
    chat_half = {}
    for i in items:
        assert chat_half.setdefault(i["case"], i["half"]) == i["half"]


def test_the_pick_is_the_same_for_the_same_seed_and_differs_for_another(gc):
    first = [(i["case"], i["turn"]) for i in gc.select_turns(_results(), _cases(), n=20, seed=0)]
    again = [(i["case"], i["turn"]) for i in gc.select_turns(_results(), _cases(), n=20, seed=0)]
    other = [(i["case"], i["turn"]) for i in gc.select_turns(_results(), _cases(), n=20, seed=1)]

    assert first == again
    assert first != other


def test_each_item_carries_both_answers_the_gold_and_the_earlier_questions(gc):
    items = gc.select_turns(_results(), _cases(), n=20, seed=0)
    item = next(i for i in items if i["turn"] == 3)
    c = item["case"][1:]

    assert item["answers"]["E"]["answer"] == f"E answer {c}.3"
    assert item["answers"]["G"]["answer"] == f"G answer {c}.3"
    assert item["question"] == f"question {c}.3"
    assert item["earlier"] == [f"question {c}.1", f"question {c}.2"]
    assert f"fact {c}.3" in item["gold"]


def test_turns_missing_either_answer_are_not_picked(gc):
    rows = [r for r in _results() if not (r["case"] == "N1" and r["mode"] == "G")]

    items = gc.select_turns(rows, _cases(), n=20, seed=0)

    assert "N1" not in {i["case"] for i in items}


# --- the sheet and its key --------------------------------------------------------


def test_sides_are_shuffled_and_the_key_records_them(gc):
    items = gc.select_turns(_results(), _cases(), n=20, seed=0)

    key = gc.assign_sides(items, random.Random(0))

    assert set(key) == set(range(1, 21))
    assert all(set(sides.values()) == {"E", "G"} for sides in key.values())
    assert {sides["A"] for sides in key.values()} == {"E", "G"}  # not always the same side


def test_the_sheet_shows_answers_on_their_sides_and_never_names_a_system_or_the_judge(gc):
    items = gc.select_turns(_results(), _cases(), n=20, seed=0)
    key = gc.assign_sides(items, random.Random(0))

    html = gc.render_sheet(items, key)

    first = items[0]
    a_mode = key[1]["A"]
    assert html.index(first["answers"][a_mode]["answer"]) < html.index(first["answers"][key[1]["B"]]["answer"])
    assert first["gold"] in html
    for word in ("shipped", "no-search", "judge", '"E"', '"G"', "tune", "report"):
        assert word not in html
    assert gc.RUBRIC.splitlines()[0] in html


def test_the_sheet_escapes_answer_text(gc):
    rows = _results(chats=2)
    rows[0]["answer"] = "<script>alert(1)</script>"
    items = gc.select_turns(rows, _cases(chats=2), n=4, seed=0)

    html = gc.render_sheet(items, gc.assign_sides(items, random.Random(0)))

    assert "<script>alert(1)</script>" not in html


# --- reading grades back ---------------------------------------------------------


def test_grades_are_read_back_by_system(gc):
    key = {1: {"A": "E", "B": "G"}, 2: {"A": "G", "B": "E"}}
    csv_text = "n,grade_a,grade_b,better,note\n1,good,bad,A,\n2,ok,good,B,\"fine, short\"\n"

    human = gc.read_grades(csv_text, key)

    assert human[1] == {"E": "good", "G": "bad", "better": "E"}
    assert human[2] == {"E": "good", "G": "ok", "better": "E"}


def test_a_tie_and_ungraded_rows(gc):
    key = {1: {"A": "E", "B": "G"}, 2: {"A": "G", "B": "E"}}

    human = gc.read_grades("n,grade_a,grade_b,better,note\n1,ok,ok,tie,\n2,,,,\n", key)

    assert human == {1: {"E": "ok", "G": "ok", "better": "tie"}}


def test_a_grade_that_isnt_on_the_scale_is_an_error(gc):
    with pytest.raises(ValueError, match="row 1"):
        gc.read_grades("n,grade_a,grade_b,better,note\n1,great,bad,A,\n", {1: {"A": "E", "B": "G"}})


# --- agreement --------------------------------------------------------------------


def test_kappa_is_one_for_identical_grades_and_zero_at_chance(gc):
    assert gc.cohen_kappa(["good", "ok", "bad"], ["good", "ok", "bad"]) == pytest.approx(1.0)
    # Every pairing equally often: observed agreement equals chance.
    assert gc.cohen_kappa(["good", "good", "bad", "bad"], ["good", "bad", "good", "bad"]) == pytest.approx(0.0)


def test_kappa_with_one_label_on_both_sides_is_undefined(gc):
    assert gc.cohen_kappa(["good", "good"], ["good", "good"]) is None


def test_a_pairwise_verdict_counts_only_if_it_survives_swapping_the_answers(gc):
    assert gc.combine_orders("E", "E") == "E"
    assert gc.combine_orders("E", "G") == "tie"  # it followed the position, not the answer
    assert gc.combine_orders("tie", "E") == "tie"


def test_preference_from_two_grades(gc):
    assert gc.preference("good", "ok") == "E"
    assert gc.preference("bad", "ok") == "G"
    assert gc.preference("ok", "ok") == "tie"


def test_agreement_is_reported_per_half(gc):
    items = [{"n": 1, "half": "tune"}, {"n": 2, "half": "tune"}, {"n": 3, "half": "report"}]
    human = {
        1: {"E": "good", "G": "bad", "better": "E"},
        2: {"E": "ok", "G": "bad", "better": "E"},
        3: {"E": "good", "G": "ok", "better": "E"},
    }
    judged = {
        1: {"pointwise": {"E": "good", "G": "bad"}, "pairwise": "E"},
        2: {"pointwise": {"E": "bad", "G": "bad"}, "pairwise": "tie"},
        3: {"pointwise": {"E": "good", "G": "ok"}, "pairwise": "E"},
    }

    tune = gc.agreement(items, human, judged, half="tune")

    assert tune["turns"] == 2
    assert tune["pointwise"]["answers"] == 4
    assert tune["pointwise"]["exact"] == 3  # E on turn 2 is the only miss
    assert tune["pointwise"]["confusion"]["ok"]["bad"] == 1  # human ok, judge bad
    assert tune["pairwise"] == {"turns": 2, "agree": 1}
    assert tune["pointwise_as_pairs"] == {"turns": 2, "agree": 1}  # turn 2: bad vs bad is a tie
    assert gc.agreement(items, human, judged, half="report")["turns"] == 1


def test_the_committed_grades_hold_no_course_text(gc):
    items = gc.select_turns(_results(), _cases(), n=20, seed=0)
    human = {i["n"]: {"E": "good", "G": "bad", "better": "E"} for i in items}

    rows = gc.shareable_grades(items, human)

    assert set(rows[0]) == {"case", "turn", "half", "human_E", "human_G", "human_better"}
    assert not any("answer" in str(v) or "question" in str(v) for r in rows for v in r.values())
