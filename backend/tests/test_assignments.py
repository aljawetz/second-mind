"""assignments.py: what list_assignments (the plugin's MCP tool) returns.

Canvas is replaced by plain dicts shaped like GET /courses/:id/assignments
with include[]=submission, so the window, status, rubric and fallback logic
is tested without a network. canvas.py's own HTTP behavior is covered in
test_canvas.py.
"""

from datetime import datetime, timedelta, timezone

import assignments

NOW = datetime(2026, 11, 14, 17, 0, tzinfo=timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _a(aid, name, due=None, submission=None, **extra):
    row = {
        "id": aid,
        "name": name,
        "due_at": _iso(due) if due else None,
        "points_possible": 50,
        "html_url": f"https://canvas.example.edu/courses/1/assignments/{aid}",
        "description": "<p>Write <b>tests</b>.</p>",
    }
    if submission is not None:
        row["submission"] = submission
    row.update(extra)
    return row


UNSUBMITTED = {"workflow_state": "unsubmitted", "late": False, "missing": False, "score": None, "grade": None}
SUBMITTED = {"workflow_state": "submitted", "late": False, "missing": False, "score": None, "grade": None}
GRADED = {"workflow_state": "graded", "late": True, "missing": False, "score": 42.0, "grade": "42", "submitted_at": "2026-11-02T03:00:00Z"}


def test_upcoming_keeps_the_window_sorted_by_due_date():
    raw = [
        _a(1, "Lab 4", NOW + timedelta(days=6), UNSUBMITTED),
        _a(2, "Lab 3", NOW + timedelta(days=2), UNSUBMITTED),
        _a(3, "Final project", NOW + timedelta(days=30), UNSUBMITTED),
        _a(4, "Reading quiz", None, UNSUBMITTED),
    ]

    out = assignments.upcoming(raw, days=7, now=NOW)

    assert [a["name"] for a in out["assignments"]] == ["Lab 3", "Lab 4"]
    assert out["days"] == 7
    assert out["as_of"] == "2026-11-14T17:00:00Z"
    assert out["assignments"][0]["url"].endswith("/assignments/2")


def test_upcoming_hides_submitted_work_unless_asked():
    raw = [_a(1, "Lab 3", NOW + timedelta(days=2), SUBMITTED), _a(2, "Lab 4", NOW + timedelta(days=3), UNSUBMITTED)]

    assert [a["name"] for a in assignments.upcoming(raw, days=7, now=NOW)["assignments"]] == ["Lab 4"]
    shown = assignments.upcoming(raw, days=7, include_submitted=True, now=NOW)["assignments"]
    assert [(a["name"], a["status"]) for a in shown] == [("Lab 3", "submitted"), ("Lab 4", "not submitted")]


def test_upcoming_shows_recent_missed_work_as_overdue():
    raw = [
        _a(1, "Missed lab", NOW - timedelta(days=3), {**UNSUBMITTED, "missing": True}),
        _a(2, "Old lab", NOW - timedelta(days=20), {**UNSUBMITTED, "missing": True}),
        _a(3, "Done lab", NOW - timedelta(days=2), SUBMITTED),
    ]

    shown = assignments.upcoming(raw, days=7, now=NOW)["assignments"]

    assert [(a["name"], a["status"]) for a in shown] == [("Missed lab", "past due, not submitted")]


def test_upcoming_clamps_days_and_caps_rows():
    raw = [_a(i, f"Item {i:02d}", NOW + timedelta(hours=i), UNSUBMITTED) for i in range(1, 20)]

    out = assignments.upcoming(raw, days=999, now=NOW)

    assert out["days"] == assignments.MAX_DAYS
    assert len(out["assignments"]) == assignments.MAX_ROWS
    assert out["more"] == 19 - assignments.MAX_ROWS
    assert assignments.upcoming(raw, days=0, now=NOW)["days"] == 1


def test_scores_are_shown_for_graded_work():
    raw = [_a(1, "Lab 2", NOW - timedelta(days=1), GRADED)]

    row = assignments.upcoming(raw, days=7, include_submitted=True, now=NOW)["assignments"][0]

    assert row["status"] == "graded"
    assert row["score"] == 42.0
    assert row["points_possible"] == 50
    assert row["late"] is True


def test_detail_has_text_rubric_submission_and_dates():
    raw = _a(
        7,
        "Task 4 deliverable",
        NOW + timedelta(days=5),
        GRADED,
        description="<h2>What to submit</h2><p>A <b>prototype</b> and a report.</p><script>x()</script>",
        unlock_at="2026-11-01T04:00:00Z",
        lock_at=None,
        use_rubric_for_grading=True,
        rubric_settings={"points_possible": 50},
        rubric=[
            {"id": "c1", "description": "Prototype", "long_description": "Covers the main flows", "points": 30,
             "ratings": [{"description": "Full", "points": 30}, {"description": "Partial", "points": 15}]},
            {"id": "c2", "description": "Report", "points": 20, "ratings": None},
        ],
    )

    out = assignments.detail(raw)

    assert out["name"] == "Task 4 deliverable"
    assert "A prototype and a report." in out["description"]
    assert "x()" not in out["description"]
    assert out["rubric"]["used_for_grading"] is True
    assert out["rubric"]["points_possible"] == 50
    assert out["rubric"]["criteria"] == [
        {"criterion": "Prototype", "detail": "Covers the main flows", "points": 30,
         "ratings": [{"rating": "Full", "points": 30}, {"rating": "Partial", "points": 15}]},
        {"criterion": "Report", "detail": "", "points": 20, "ratings": []},
    ]
    assert out["submission"] == {"status": "graded", "score": 42.0, "grade": "42", "late": True, "missing": False,
                                 "submitted_at": "2026-11-02T03:00:00Z"}
    assert out["unlock_at"] == "2026-11-01T04:00:00Z"
    assert out["url"].endswith("/assignments/7")


def test_detail_without_a_rubric_says_so():
    out = assignments.detail(_a(8, "Reading response", None, UNSUBMITTED))

    assert out["rubric"] is None
    assert out["due_at"] is None


def test_detail_caps_a_long_description():
    out = assignments.detail(_a(9, "Essay", None, UNSUBMITTED, description="<p>" + "word " * 5000 + "</p>"))

    assert len(out["description"]) <= assignments.DESCRIPTION_CHARS + 1


def test_fallback_reads_due_lines_from_indexed_assignments():
    rows = [
        {"doc_id": "assignment:11", "text": "Due date and points\nDue Fri, Nov 20, 2026 at 11:59 PM EST. Worth 50 points.\nWhat to do...",
         "metadata": {"source": "Lab 3: Branch Coverage", "item_type": "assignment"}},
        {"doc_id": "assignment:11", "text": "More of the description", "metadata": {"source": "Lab 3: Branch Coverage", "item_type": "assignment"}},
        {"doc_id": "file:5", "text": "Due Fri, Nov 20, 2026 at noon.", "metadata": {"source": "syllabus.pdf", "item_type": "file"}},
        {"doc_id": "assignment:12", "text": "No date here", "metadata": {"source": "Participation", "item_type": "assignment"}},
    ]

    out = assignments.from_index_rows(rows, reason="Canvas could not be reached")

    assert out["stale"] is True
    assert "Canvas could not be reached" in out["note"]
    assert out["assignments"] == [
        {"name": "Lab 3: Branch Coverage", "schedule": "Due Fri, Nov 20, 2026 at 11:59 PM EST. Worth 50 points."}
    ]
