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

import os
import re
from datetime import datetime, timedelta, timezone, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_DAYS = 14
MAX_DAYS = 60
OVERDUE_DAYS = 7
MAX_ROWS = 12
# Assignment descriptions run long (whole specs pasted into Canvas); the
# rubric and dates matter more than the tail of the prose.
DESCRIPTION_CHARS = 4000

# Canvas sends UTC. The model must never convert it: in testing it picked
# the wrong zone (from the canvas.cmu.edu URL) and then did the arithmetic
# wrong too. So every time leaves the server already in the student's zone,
# as a display string to copy, with "in 2 days, 14 hours" next to it.


def machine_zone() -> tzinfo:
    """The zone this machine runs in: TZ, else /etc/localtime's target (macOS
    and most Linux), else the OS's fixed offset."""
    for name in (os.environ.get("TZ"), _localtime_name()):
        if name:
            try:
                return ZoneInfo(name)
            except (ZoneInfoNotFoundError, ValueError):
                pass
    return datetime.now().astimezone().tzinfo


def _localtime_name() -> str | None:
    try:
        target = os.readlink("/etc/localtime")
    except OSError:
        return None
    _, sep, name = target.partition("zoneinfo/")
    return name if sep else None


def zone_from_name(name: str | None) -> tzinfo:
    """Canvas's profile time_zone (an IANA name), else the machine's zone."""
    if name:
        try:
            return ZoneInfo(name)
        except (ZoneInfoNotFoundError, ValueError):
            pass
    return machine_zone()


def zone_name(tz: tzinfo) -> str:
    return getattr(tz, "key", None) or datetime.now(tz).tzname() or "local"


def _span(seconds: float) -> str:
    minutes = int(abs(seconds) // 60)
    days, rest = divmod(minutes, 24 * 60)
    hours, minutes = divmod(rest, 60)
    plural = lambda n, unit: f"{n} {unit}{'' if n == 1 else 's'}"
    if days:
        parts = [plural(days, "day")] + ([plural(hours, "hour")] if hours else [])
    elif hours:
        parts = [plural(hours, "hour")]
    elif minutes:
        parts = [plural(minutes, "minute")]
    else:
        return "less than a minute"
    return ", ".join(parts)


def when(moment: datetime, tz: tzinfo, now: datetime | None = None) -> dict:
    """One time, three ways: UTC (for reference), local ISO with offset, and
    the string to show the student. Plus how far away it is."""
    now = now or datetime.now(timezone.utc)
    local = moment.astimezone(tz)
    seconds = (moment - now).total_seconds()
    span = _span(seconds)
    return {
        "due_at_utc": moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "due_at_local": local.isoformat(),
        "due_at_display": f"{local:%a, %b} {local.day}, {local.hour % 12 or 12}:{local:%M %p} {local.tzname()}",
        "due_in": f"in {span}" if seconds >= 0 else f"{span} ago",
    }


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


_DUE_LINE = re.compile(r"Due [A-Z][a-z]{2}, [A-Z][a-z]{2} \d{1,2}, \d{4}[^\n]*")


def _due(assignment: dict) -> datetime | None:
    return _parse(assignment.get("due_at"))


def _status(assignment: dict, now: datetime) -> str:
    submission = assignment.get("submission") or {}
    state = submission.get("workflow_state")
    if state == "graded":
        return "graded"
    if state not in (None, "unsubmitted"):
        return "submitted"
    due = _due(assignment)
    return "past due, not submitted" if due and due < now else "not submitted"


def _row(assignment: dict, now: datetime, tz: tzinfo) -> dict:
    submission = assignment.get("submission") or {}
    due = _due(assignment)
    return {
        "assignment_id": assignment["id"],
        "name": assignment.get("name") or f"Assignment {assignment['id']}",
        **(when(due, tz, now) if due else {}),
        "points_possible": assignment.get("points_possible"),
        "status": _status(assignment, now),
        "score": submission.get("score"),
        "late": bool(submission.get("late")),
        "missing": bool(submission.get("missing")),
        "url": assignment.get("html_url"),
    }


def upcoming(raw: list[dict], days: int = DEFAULT_DAYS, only_unsubmitted: bool = False, now: datetime | None = None,
             tz: tzinfo | None = None) -> dict:
    """raw: canvas.list_assignments() rows. Every assignment due from
    OVERDUE_DAYS ago to `days` days ahead, submitted or not, each with its
    status, soonest first; the student asks a follow-up to narrow it. With
    only_unsubmitted, just the work still to hand in."""
    now = now or datetime.now(timezone.utc)
    tz = tz or machine_zone()
    days = min(max(int(days), 1), MAX_DAYS)
    start, end = now - timedelta(days=OVERDUE_DAYS), now + timedelta(days=days)
    rows = []
    for a in raw:
        due = _due(a)
        if due is None or not start <= due <= end:
            continue
        row = _row(a, now, tz)
        done = row["status"] in ("submitted", "graded")
        if done and only_unsubmitted:
            continue
        rows.append((due, row))
    rows.sort(key=lambda pair: pair[0])
    out = {
        "as_of": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "timezone": zone_name(tz),
        "days": days,
        "assignments": [r for _, r in rows[:MAX_ROWS]],
    }
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


def detail(assignment: dict, now: datetime | None = None, tz: tzinfo | None = None) -> dict:
    """One assignment in full: what to hand in, how it is graded, and where
    the student stands. The score and grade are the student's own."""
    now = now or datetime.now(timezone.utc)
    tz = tz or machine_zone()
    submission = assignment.get("submission") or {}

    def local(key: str) -> dict | None:
        moment = _parse(assignment.get(key))
        return when(moment, tz, now) if moment else None

    description = _text(assignment.get("description") or "")
    if len(description) > DESCRIPTION_CHARS:
        description = description[:DESCRIPTION_CHARS] + "…"
    return {
        "assignment_id": assignment["id"],
        "name": assignment.get("name") or f"Assignment {assignment['id']}",
        "timezone": zone_name(tz),
        "due": local("due_at"),
        "unlock": local("unlock_at"),
        "lock": local("lock_at"),
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
