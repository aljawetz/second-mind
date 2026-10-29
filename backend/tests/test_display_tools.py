"""display_tools.py — the deadlines card's data, built from Canvas rows with
a fixed clock. No network."""

from datetime import datetime, timedelta, timezone

import display_tools

NOW = datetime(2026, 10, 28, 12, 0, tzinfo=timezone.utc)


def _a(id_, name, due_in_days, submitted=False, points=10):
    due = None if due_in_days is None else (NOW + timedelta(days=due_in_days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {"id": id_, "name": name, "due_at": due, "points_possible": points, "submitted": submitted, "late": False, "missing": False}


def test_shows_unsubmitted_work_due_in_the_window_soonest_first():
    rows = [_a(1, "Essay", 10), _a(2, "Lab", 2), _a(3, "Final project", 30), _a(4, "Reading", None)]
    props, text = display_tools.deadlines(rows, {}, NOW)
    assert [a["name"] for a in props["assignments"]] == ["Lab", "Essay"]
    assert props["days"] == 14
    assert props["as_of"] == "2026-10-28T12:00:00Z"
    assert "2 assignment(s) in the next 14 days" in text
    assert "Lab: due" in text and "not submitted" in text


def test_recently_missed_work_shows_but_old_or_submitted_past_work_does_not():
    rows = [_a(1, "Missed quiz", -3), _a(2, "Ancient HW", -20), _a(3, "Done HW", -1, submitted=True)]
    props, text = display_tools.deadlines(rows, {}, NOW)
    assert [a["name"] for a in props["assignments"]] == ["Missed quiz"]
    assert "past due, not submitted" in text


def test_submitted_upcoming_work_only_when_asked():
    rows = [_a(1, "Early bird", 3, submitted=True)]
    assert display_tools.deadlines(rows, {}, NOW)[0]["assignments"] == []
    props, text = display_tools.deadlines(rows, {"include_submitted": True}, NOW)
    assert [a["name"] for a in props["assignments"]] == ["Early bird"]
    assert "submitted." in text


def test_days_is_clamped_and_bad_values_fall_back_to_the_default():
    rows = [_a(1, "Far", 50)]
    assert display_tools.deadlines(rows, {"days": 7}, NOW)[0]["assignments"] == []
    assert display_tools.deadlines(rows, {"days": 500}, NOW)[0]["days"] == display_tools.MAX_DAYS
    assert display_tools.deadlines(rows, {"days": 0}, NOW)[0]["days"] == 1
    assert display_tools.deadlines(rows, {"days": "soon"}, NOW)[0]["days"] == 14
    assert display_tools.deadlines(rows, {"days": True}, NOW)[0]["days"] == 14


def test_at_most_max_rows_with_a_note_for_the_model():
    rows = [_a(i, f"HW {i}", 1 + i * 0.1) for i in range(15)]
    props, text = display_tools.deadlines(rows, {}, NOW)
    assert len(props["assignments"]) == display_tools.MAX_ROWS
    assert "(3 more not shown.)" in text


def test_nothing_due_is_still_a_card():
    props, text = display_tools.deadlines([], {"days": 7}, NOW)
    assert props["assignments"] == []
    assert "nothing due in the next 7 days" in text


def test_card_rows_carry_only_the_fields_the_app_uses():
    row = {**_a(1, "Lab", 2), "description": "<p>long</p>", "html_url": "x"}
    [shown] = display_tools.deadlines([row], {}, NOW)[0]["assignments"]
    assert set(shown) == set(display_tools.ASSIGNMENT_FIELDS)


def test_history_note_lists_what_a_card_showed():
    props, _ = display_tools.deadlines([_a(1, "Lab", 2)], {}, NOW)
    note = display_tools.history_note([{"id": "ui-1", "component": "deadlines", "props": props}])
    assert note.startswith("\n\n[Deadlines card shown: Lab (due 2026-10-30T12:00:00Z)")
    assert display_tools.history_note(None) == ""
    assert "nothing due" in display_tools.history_note([{"component": "deadlines", "props": {"assignments": []}}])
