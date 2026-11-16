"""Relative dates in a search query ("next week", "tomorrow"), shared by the
app's chat (chat.py) and the Claude Code plugin's search (mcp_server.py),
which must not import chat.py and its LLM stack."""

import datetime
import re

_RELATIVE_DAYS = {"today": (0, 0), "tomorrow": (1, 1)}


def expand_relative_dates(query: str, today: datetime.date) -> str:
    """Course pages say "Due Wed, Oct 28, 2026", never "next week", so a
    search for "what is due next week?" misses them (seen in the Sprint 8
    eval). Add the real dates after the student's words: today, tomorrow,
    this week and next week (Monday to Sunday). A query with none of those
    words comes back unchanged."""
    text = query.lower()
    days: list[datetime.date] = []
    monday = today - datetime.timedelta(days=today.weekday())
    for phrase, (start, end) in _RELATIVE_DAYS.items():
        if re.search(rf"\b{phrase}\b", text):
            days += [today + datetime.timedelta(days=d) for d in range(start, end + 1)]
    if re.search(r"\bthis week\b", text):
        days += [monday + datetime.timedelta(days=d) for d in range(7)]
    if re.search(r"\bnext week\b", text):
        days += [monday + datetime.timedelta(days=7 + d) for d in range(7)]
    if not days:
        return query
    dates = " ".join(f"{d:%b} {d.day}" for d in dict.fromkeys(days))
    return f"{query} {dates} {days[-1].year}"
