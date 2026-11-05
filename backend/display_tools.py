"""Display tools for course chat: cards the model can put below its answer.
Plan: docs/plans/2026-10-28-chat-generative-ui.md.

The model picks a card and passes a few arguments. What the card shows is
built here from real data (Canvas, the study generator), never from the
model's own text, and the app renders it with a component from a fixed set.
So the model can choose to show a deadlines card but can't put a made-up
assignment in it.

Each tool returns the card's props and a short text for the model, so it
knows what the student sees and can add to it instead of repeating it.
"""

from datetime import datetime, timedelta, timezone

DEADLINES_TOOL = {
    "type": "function",
    "function": {
        "name": "show_deadlines",
        "description": (
            "Show the student a card below your answer with their Canvas assignments due soon, each with its due "
            "date, countdown and whether they've submitted it. Use when they ask what's due, about upcoming "
            "deadlines, or what to work on next."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "description": "How many days ahead to show. Default 14. Use 7 for 'this week'.",
                },
                "include_submitted": {
                    "type": "boolean",
                    "description": "Also list assignments they've already submitted. Default false.",
                },
            },
        },
    },
}

RULES = """

You can also show the student cards below your answer. They appear after your text.
- show_deadlines: their assignments due soon, straight from Canvas, with submission status. Call it when \
they ask what's due, about upcoming deadlines, or what to work on next. Don't call it for a question about one \
assignment's content or rules, or for exam dates (search for those).
- Each card can be shown once per answer. The card's dates come from Canvas, so you can mention them without a \
citation. Don't list the card's contents again in your text. Add what helps instead (what to start first and \
why), and cite course material for anything else as usual."""

DEFAULT_DAYS = 14
MAX_DAYS = 60
# Unsubmitted work this recently past due still shows, marked late: "what's
# due?" should surface a missed assignment, not hide it.
OVERDUE_DAYS = 7
MAX_ROWS = 12

ASSIGNMENT_FIELDS = ("id", "name", "due_at", "points_possible", "submitted", "late", "missing")


def _due(assignment: dict) -> datetime | None:
    due_at = assignment.get("due_at")
    if not due_at:
        return None
    try:
        return datetime.fromisoformat(due_at.replace("Z", "+00:00"))
    except ValueError:
        return None


def _when(assignment: dict) -> str:
    """"due Fri, Oct 31 at 11:59 PM EDT, 20 points", in the student's own
    time zone (the backend runs on their machine), like course_sync's
    schedule_line. Not imported from there: course_sync loads the indexer."""
    due = _due(assignment).astimezone()
    text = f"due {due.strftime('%a, %b')} {due.day} at {due.strftime('%I:%M %p %Z').lstrip('0')}"
    points = assignment.get("points_possible")
    if isinstance(points, (int, float)) and points > 0:
        text += f", {points:g} points"
    return text


def deadlines(assignments: list[dict], args: dict, now: datetime | None = None) -> tuple[dict, str]:
    """assignments: canvas.assignment_summary() rows. Returns the card's
    props and the text the model gets back. Undated assignments are left
    out: they can't be due soon."""
    now = now or datetime.now(timezone.utc)
    days = args.get("days")
    days = min(max(days, 1), MAX_DAYS) if isinstance(days, int) and not isinstance(days, bool) else DEFAULT_DAYS
    include_submitted = args.get("include_submitted") is True
    start, end = now - timedelta(days=OVERDUE_DAYS), now + timedelta(days=days)

    rows = []
    for a in assignments:
        due = _due(a)
        if due is None or not start <= due <= end:
            continue
        if a.get("submitted") and not include_submitted:
            continue
        if due < now and a.get("submitted"):
            continue
        rows.append((due, a))
    rows.sort(key=lambda row: row[0])
    shown = [{k: a.get(k) for k in ASSIGNMENT_FIELDS} for _, a in rows[:MAX_ROWS]]

    props = {"as_of": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "days": days, "assignments": shown}
    if not shown:
        return props, f"Shown to the student below your answer: nothing due in the next {days} days."
    lines = [f"Shown to the student below your answer, {len(shown)} assignment(s) in the next {days} days:"]
    for a in shown:
        status = "submitted" if a["submitted"] else "past due, not submitted" if _due(a) < now else "not submitted"
        lines.append(f"- {a['name']}: {_when(a)}, {status}.")
    if len(rows) > MAX_ROWS:
        lines.append(f"({len(rows) - MAX_ROWS} more not shown.)")
    # Said here as well as in RULES: in the first live run the model listed
    # every row again in its text with only the system prompt telling it not to.
    lines.append(
        "The student already sees these with their dates and status. Don't list them again. In a sentence or two, "
        "say what to start first and why."
    )
    return props, "\n".join(lines)


def history_note(ui: list[dict] | None) -> str:
    """What a saved turn's cards showed, appended to its answer in the chat
    history, so a follow-up ("which of those is worth the most?") can see
    them. The answer text alone doesn't list them, by design."""
    notes = []
    for block in ui or []:
        if block.get("component") == "deadlines":
            names = [f"{a['name']} (due {a['due_at'] or 'no date'})" for a in block["props"]["assignments"]]
            notes.append("[Deadlines card shown: " + ("; ".join(names) or "nothing due") + "]")
    return "".join("\n\n" + note for note in notes)
