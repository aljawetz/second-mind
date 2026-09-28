"""Extraction — design spec §5.2. One LLM call turns chat turns into
candidate memories and rewrites the conversation's summary, which is what
lets the product spend one background call per turn.

The same function takes one turn (the app) or a whole session (the
LongMemEval replay, evaluation spec §4.3).
"""

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol


class JsonLLM(Protocol):
    def complete_json(self, messages: list[dict]) -> object:
        """One non-streaming call; the reply parsed as JSON."""
        ...


@dataclass
class Candidate:
    kind: str
    text: str
    importance: int
    event_time: datetime | None
    entities: list[str]
    task_ref_hint: str | None


@dataclass
class Extraction:
    memories: list[Candidate]
    summary: str
    dropped: list[tuple[str, str]] = field(default_factory=list)  # (text, reason)


SYSTEM_PROMPT = """You keep Second Mind's memory of one student in one course. Read the \
conversation and write down what will be worth knowing about the student in later conversations.

Record three kinds of memory:
- fact: a stable fact about the student, or a preference ("The student is on team 4 with Priya \
and Ken.", "The student wants code examples in Java.")
- event: something that happened to the student at a particular time ("On 2026-09-22 the \
student missed Class #5.")
- task: the student's own goal or progress on their course work ("The student finished part 1 \
of Assignment 3 and is stuck mocking the email service.")

Rules:
- Only record what the student said or clearly confirmed. The assistant's suggestions and \
explanations are not facts about the student.
- Each memory is one sentence in the third person that makes sense on its own. Replace "it", \
"that one" and relative dates with what they mean; use the conversation's date to turn \
"yesterday" or "last Tuesday" into a date.
- Skip facts about the course itself (dates, grading, policies, content): the course materials \
already hold those. Skip small talk and anything the summary already records.
- Never write down grades, scores or deadlines, in memories or the summary.
- importance: 1 (trivia) to 5 (the student would expect you to always remember it).
- event_time: the date (YYYY-MM-DD) it happened or became true, if known.
- entities: the people, assignments, projects and topics it mentions, as short lowercase names.
- task_ref_hint: for a task, the assignment or project it is about; otherwise null.
- Returning no memories is fine.

Also rewrite the summary of the whole conversation so far, including this part, in at most 150 \
words.

Reply with JSON only:
{"memories": [{"kind": ..., "text": ..., "importance": ..., "event_time": ..., "entities": [...], \
"task_ref_hint": ...}], "summary": "..."}"""

# "summary" is a memory kind too, but compression writes those, not this.
KINDS = ("fact", "event", "task")
MAX_PER_TURN = 5
MAX_TEXT_CHARS = 300
MAX_SUMMARY_WORDS = 150
DEFAULT_IMPORTANCE = 3

# Design spec §5.2: grades and deadlines are never indexed, so they're never
# remembered either, whatever the model returns. Cautious on purpose ("was
# graded harshly" goes too); the evaluation counts what this drops wrongly.
_GRADES_OR_DEADLINES = [
    re.compile(r"\b(grades?|graded|grading|gpa|scored?|scores|marks)\b", re.IGNORECASE),
    # "got a B+", "received an A-". The letter is case-sensitive, so "got a
    # book" isn't a grade, and it must end there: "got a B-tree" isn't either.
    re.compile(r"\b(?i:got|gets?|getting|received|earned|lost)\s+(?:an?\s+)?[A-DF][+-]?(?=[\s.,;:!?)]|$)"),
    # "got a 72 on the midterm", "lost 10 points", "received 18/20".
    re.compile(r"\b(got|received|earned|lost)\b[^.]{0,30}?\b\d{1,3}(?:\.\d+)?\b", re.IGNORECASE),
    re.compile(r"\b(due|overdue|deadlines?)\b", re.IGNORECASE),
]
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")

_SPEAKERS = {"user": "Student", "assistant": "Assistant"}

# [3], [1, 4]: numbers of search results the extractor never sees. Same
# shape chat.py's CitationRenumberer rewrites; the space before goes too.
_CITATION = re.compile(r"\s?\[\s*\d+(?:\s*,\s*\d+)*\s*\]")


def extract(messages: list[dict], *, at: datetime, summary: str, llm: JsonLLM) -> Extraction:
    """messages: [{"role": "user" | "assistant", "content"}], oldest first.
    at: when they were said. summary: the conversation's summary before them."""
    reply = llm.complete_json(
        [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": _prompt(messages, at, summary)}]
    )
    # This runs in the background worker: a reply of the wrong shape gives
    # no memories and keeps the old summary, instead of raising.
    if not isinstance(reply, dict):
        reply = {}
    items = reply.get("memories")

    # Rules the prompt states but code enforces (design spec §6). The limit
    # is per student turn, so a replayed session isn't cut to one turn's worth.
    limit = MAX_PER_TURN * max(1, sum(m["role"] == "user" for m in messages))
    memories: list[Candidate] = []
    dropped: list[tuple[str, str]] = []
    seen: set[str] = set()
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            dropped.append(("", "malformed"))
            continue
        text = item.get("text")
        text = text.strip()[:MAX_TEXT_CHARS] if isinstance(text, str) else ""
        if not text:
            reason = "empty"
        elif item.get("kind") not in KINDS:
            reason = "kind"
        elif any(p.search(text) for p in _GRADES_OR_DEADLINES):
            reason = "grades_or_deadlines"
        elif text.casefold() in seen:
            reason = "duplicate"
        elif len(memories) >= limit:
            reason = "limit"
        else:
            reason = None
        if reason:
            dropped.append((text, reason))
            continue
        seen.add(text.casefold())
        memories.append(
            Candidate(
                kind=item["kind"],
                text=text,
                importance=_importance(item.get("importance")),
                event_time=_parse_time(item.get("event_time"), at),
                entities=_entities(item.get("entities")),
                task_ref_hint=_name(item.get("task_ref_hint")),
            )
        )
    new_summary = reply.get("summary")
    if isinstance(new_summary, str):
        # The summary becomes a recallable memory too (design spec §5.6), so
        # the grades rule applies to it, one sentence at a time.
        kept = []
        for sentence in _SENTENCE_END.split(" ".join(new_summary.split())):
            if any(p.search(sentence) for p in _GRADES_OR_DEADLINES):
                dropped.append((sentence, "grades_or_deadlines"))
            elif sentence:
                kept.append(sentence)
        if kept:
            summary = " ".join(" ".join(kept).split()[:MAX_SUMMARY_WORDS])
    return Extraction(memories=memories, summary=summary, dropped=dropped)


def _prompt(messages: list[dict], at: datetime, summary: str) -> str:
    conversation = "\n".join(
        f"{_SPEAKERS.get(m['role'], m['role'])}: {_CITATION.sub('', m['content'])}" for m in messages
    )
    # The weekday too, so "last Tuesday" can become a date.
    return (
        f"Date of this conversation: {at.strftime('%A %Y-%m-%d %H:%M %Z')}\n"
        f"Summary of the conversation so far: {summary or '(none yet)'}\n\n"
        f"Conversation:\n{conversation}"
    )


def _importance(value) -> int:
    try:
        return min(max(int(value), 1), 5)
    except (TypeError, ValueError):
        return DEFAULT_IMPORTANCE


def _entities(value) -> list[str]:
    if not isinstance(value, list):
        return []
    return [e.strip() for e in value if isinstance(e, str) and e.strip()]


def _name(value) -> str | None:
    if not isinstance(value, str):
        return None
    return value.strip() or None


def _parse_time(value, at: datetime) -> datetime:
    """An ISO date or datetime from the model. Anything else ("last week",
    nothing) falls back to when it was said: the one time the memory is
    known to have been true."""
    if not isinstance(value, str):
        return at
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError:
        return at
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=at.tzinfo)
