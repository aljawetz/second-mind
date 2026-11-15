"""Assignments for the plugin's list_assignments tool (plan
docs/plans/2026-11-13-claude-code-plugin.md, Decisions 15 and 17).

Deadlines, submission status, scores and rubrics are read live from Canvas
(canvas.list_assignments, one call with include[]=submission; Canvas puts
the rubric on every assignment that has one). The index is a snapshot and
has none of the status, so it is only a fallback when Canvas can't be
reached, and says so.

The window rules follow the app's show_deadlines card (display_tools.py on
the generative UI branches, not on main): unsubmitted work up to a week past
due still shows, as missed work the student should see; undated work is left
out; at most MAX_ROWS rows.
"""

import re
from datetime import datetime, timedelta, timezone

DEFAULT_DAYS = 14
MAX_DAYS = 60
OVERDUE_DAYS = 7
MAX_ROWS = 12
# Assignment descriptions run long (whole specs pasted into Canvas); the
# rubric and dates matter more than the tail of the prose.
DESCRIPTION_CHARS = 4000

_DUE_LINE = re.compile(r"Due [A-Z][a-z]{2}, [A-Z][a-z]{2} \d{1,2}, \d{4}[^\n]*")


def _due(assignment: dict) -> datetime | None:
    due_at = assignment.get("due_at")
    if not due_at:
        return None
    try:
        return datetime.fromisoformat(due_at.replace("Z", "+00:00"))
    except ValueError:
        return None


def _status(assignment: dict, now: datetime) -> str:
    submission = assignment.get("submission") or {}
    state = submission.get("workflow_state")
    if state == "graded":
        return "graded"
    if state not in (None, "unsubmitted"):
        return "submitted"
    due = _due(assignment)
    return "past due, not submitted" if due and due < now else "not submitted"


def _row(assignment: dict, now: datetime) -> dict:
    submission = assignment.get("submission") or {}
    return {
        "assignment_id": assignment["id"],
        "name": assignment.get("name") or f"Assignment {assignment['id']}",
        "due_at": assignment.get("due_at"),
        "points_possible": assignment.get("points_possible"),
        "status": _status(assignment, now),
        "score": submission.get("score"),
        "late": bool(submission.get("late")),
        "missing": bool(submission.get("missing")),
        "url": assignment.get("html_url"),
    }


def upcoming(raw: list[dict], days: int = DEFAULT_DAYS, include_submitted: bool = False, now: datetime | None = None) -> dict:
    """raw: canvas.list_assignments() rows. Assignments due in the next
    `days` days, plus unsubmitted ones up to OVERDUE_DAYS past due, soonest
    first. Submitted or graded work only with include_submitted."""
    now = now or datetime.now(timezone.utc)
    days = min(max(int(days), 1), MAX_DAYS)
    start, end = now - timedelta(days=OVERDUE_DAYS), now + timedelta(days=days)
    rows = []
    for a in raw:
        due = _due(a)
        if due is None or not start <= due <= end:
            continue
        row = _row(a, now)
        done = row["status"] in ("submitted", "graded")
        if done and not include_submitted:
            continue
        rows.append((due, row))
    rows.sort(key=lambda pair: pair[0])
    out = {"as_of": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "days": days, "assignments": [r for _, r in rows[:MAX_ROWS]]}
    if len(rows) > MAX_ROWS:
        out["more"] = len(rows) - MAX_ROWS
    return out


def _text(html: str) -> str:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html or "", "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    text = re.sub(r"[ \t]+", " ", soup.get_text(" "))
    text = re.sub(r" *\n[\n ]*", "\n", text)
    return re.sub(r" ([.,;:!?])", r"\1", text).strip()


def _rubric(assignment: dict) -> dict | None:
    criteria = assignment.get("rubric")
    if not criteria:
        return None
    settings = assignment.get("rubric_settings") or {}
    return {
        "used_for_grading": bool(assignment.get("use_rubric_for_grading")),
        "points_possible": settings.get("points_possible"),
        "criteria": [
            {
                "criterion": c.get("description") or "",
                "detail": c.get("long_description") or "",
                "points": c.get("points"),
                "ratings": [{"rating": r.get("description") or "", "points": r.get("points")} for r in c.get("ratings") or []],
            }
            for c in criteria
        ],
    }


def detail(assignment: dict, now: datetime | None = None) -> dict:
    """One assignment in full: what to hand in, how it is graded, and where
    the student stands. The score and grade are the student's own."""
    now = now or datetime.now(timezone.utc)
    submission = assignment.get("submission") or {}
    description = _text(assignment.get("description") or "")
    if len(description) > DESCRIPTION_CHARS:
        description = description[:DESCRIPTION_CHARS] + "…"
    return {
        "assignment_id": assignment["id"],
        "name": assignment.get("name") or f"Assignment {assignment['id']}",
        "due_at": assignment.get("due_at"),
        "unlock_at": assignment.get("unlock_at"),
        "lock_at": assignment.get("lock_at"),
        "points_possible": assignment.get("points_possible"),
        "description": description,
        "rubric": _rubric(assignment),
        "submission": {
            "status": _status(assignment, now),
            "score": submission.get("score"),
            "grade": submission.get("grade"),
            "late": bool(submission.get("late")),
            "missing": bool(submission.get("missing")),
            "submitted_at": submission.get("submitted_at"),
        },
        "url": assignment.get("html_url"),
    }


def from_index_rows(rows: list[dict], reason: str) -> dict:
    """The fallback when Canvas can't be reached: the "Due ... Worth N
    points" line course_sync.schedule_line put in each indexed assignment.
    No status, and as old as the last sync."""
    seen: dict[str, dict] = {}
    for row in rows:
        metadata = row.get("metadata") or {}
        if metadata.get("item_type") != "assignment":
            continue
        doc_id = row.get("doc_id") or ""
        match = _DUE_LINE.search(row.get("text") or "")
        if match and doc_id not in seen:
            seen[doc_id] = {"name": metadata.get("source") or doc_id, "schedule": match.group(0).strip()}
    return {
        "stale": True,
        "note": (
            f"{reason}, so these due dates come from the last sync and may be out of date. "
            "Submission status is not available."
        ),
        "assignments": list(seen.values()),
    }
