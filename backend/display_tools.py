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

QUIZ_TOOL = {
    "type": "function",
    "function": {
        "name": "show_quiz",
        "description": (
            "Write a 5-question multiple-choice practice quiz from this course's own material and show it below your answer, "
            "where the student can take it. Every question cites the passage it was written from. Use when they "
            "ask to be quizzed or tested, or for practice questions."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "description": (
                        "What the quiz covers, in the student's words, like 'lecture 5' or 'user stories'. For "
                        "'quiz me on that', the subject you were just discussing. Empty for the whole course."
                    ),
                },
                "difficulty": {
                    "type": "string",
                    "enum": ["easy", "medium", "hard"],
                    "description": "Only if they ask for one. Default medium.",
                },
            },
            "required": ["topic"],
        },
    },
}

_RULES = {
    "show_deadlines": "- show_deadlines: their assignments due soon, straight from Canvas, with submission status. "
    "Call it when they ask what's due, about upcoming deadlines, or what to work on next. Don't call it for a "
    "question about one assignment's content or rules, or for exam dates (search for those). Its dates come from "
    "Canvas, so you can mention them without a citation.",
    "show_quiz": "- show_quiz: a practice quiz written from the course material, which the student takes below your "
    "answer. Call it when they ask to be quizzed or tested, or for practice questions. A practice quiz is not "
    "graded work, so this is fine. Don't call it for questions about the course's own quizzes or exams (what's on "
    "them, when they are): search for those. Never write quiz questions in your own text.",
}


def rules(tool_names: list[str]) -> str:
    """The prompt section for the display tools on offer this turn."""
    lines = [_RULES[name] for name in tool_names if name in _RULES]
    if not lines:
        return ""
    return (
        "\n\nYou can also show the student cards below your answer. They appear after your text.\n"
        + "\n".join(lines)
        + "\n- Each card can be shown once per answer. Don't repeat a card's contents in your text. Add what helps "
        "instead, and cite course material for anything else as usual."
    )

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


def quiz_options(args: dict) -> dict:
    """The model's show_quiz arguments as study.check_options input. Bad or
    missing values fall back to the defaults instead of failing: the
    student asked for a quiz, and a stray difficulty shouldn't stop it.

    Always 5 questions ("fewer"). The tool had a count argument "only if the
    student asks for more", and in the first live run gpt-4o-mini asked for
    10 on a plain "quiz me". A longer quiz is one click in the Study panel."""
    topic = args.get("topic")
    difficulty = args.get("difficulty")
    return {
        "count": "fewer",
        "difficulty": difficulty if difficulty in ("easy", "medium", "hard") else "medium",
        # study.MAX_TOPIC_CHARS; cut rather than refused.
        "topic": " ".join(topic.split())[:500] if isinstance(topic, str) else "",
    }


def quiz_started(topic: str) -> str:
    about = f"on {topic} " if topic else ""
    return (
        f"A 5-question practice quiz {about}is being written from the course material. It appears below your answer "
        "in under a minute, and the student takes it there. Don't write any questions yourself. In one sentence, say "
        "what it covers. Only if they asked for a number of questions above 5, add that a longer quiz can be made from "
        "the Study panel; otherwise don't mention it."
    )


NO_QUIZ_MATERIAL = (
    "No quiz was made: this course has nothing indexed to write questions from yet. Tell the student to sync the "
    "course or record a session first."
)


def history_note(ui: list[dict] | None) -> str:
    """What a saved turn's cards showed, appended to its answer in the chat
    history, so a follow-up ("which of those is worth the most?") can see
    them. The answer text alone doesn't list them, by design."""
    notes = []
    for block in ui or []:
        if block.get("component") == "deadlines":
            names = [f"{a['name']} (due {a['due_at'] or 'no date'})" for a in block["props"]["assignments"]]
            notes.append("[Deadlines card shown: " + ("; ".join(names) or "nothing due") + "]")
        elif block.get("component") == "quiz":
            topic = block["props"].get("topic") or "the whole course"
            notes.append(f"[Practice quiz shown, on {topic}]")
    return "".join("\n\n" + note for note in notes)
