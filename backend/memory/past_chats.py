"""Saved chat turns, indexed so another chat can search them
(search_past_chats) — docs/specs/2026-11-10-past-chat-search-design.md.

Memory keeps what the student said about themselves and never what the
assistant said, so a wrong answer can't become a remembered fact. That
leaves "which video did you recommend?" unanswerable from memory: the
memory evaluation scored it 0 to 2 of 10, against 5 of 5 for plain search
over the raw turns. This is that search, kept apart from memory: a turn is
shown as what was said in an earlier chat, not as something known.
"""

from datetime import datetime
from typing import Callable

from memory.extract import _CITATION, mentions_grades_or_deadlines
from memory.store import MemoryStore


def turn_text(question: str, answer: str) -> str:
    return f"Student: {question}\nAssistant: {answer}"


def index_turn(
    store: MemoryStore,
    embed: Callable[[str], list[float]],
    *,
    conversation_id: str,
    turn_index: int,
    title: str,
    at: datetime,
    question: str,
    answer: str,
) -> bool:
    """Make one saved turn searchable. False, with nothing kept for it, when
    it mentions grades or deadlines: the memory database holds neither
    (agent memory design §5.2), cautious on purpose."""
    # Old [n] numbers pointed at that answer's own searches.
    answer = _CITATION.sub("", answer)
    if mentions_grades_or_deadlines(question) or mentions_grades_or_deadlines(answer):
        store.delete_turn(conversation_id, turn_index)
        return False
    store.add_turn(
        conversation_id, turn_index, title=title, at=at, question=question, answer=answer,
        embedding=embed(turn_text(question, answer)),
    )
    return True
