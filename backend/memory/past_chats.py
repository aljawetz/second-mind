"""Saved chat turns, indexed so another chat can search them
(search_past_chats) — docs/specs/2026-11-10-past-chat-search-design.md.

Memory keeps what the student said about themselves and never what the
assistant said, so a wrong answer can't become a remembered fact. That
leaves "which video did you recommend?" unanswerable from memory: the
memory evaluation scored it 0 to 2 of 10, against 5 of 5 for plain search
over the raw turns. This is that search, kept apart from memory: a turn is
shown as what was said in an earlier chat, not as something known.
"""

import math
from datetime import datetime
from typing import Callable

from memory.extract import _CITATION, mentions_grades_or_deadlines
from memory.recall import KEYWORD_CANDIDATES, RECENCY_DAYS, RRF_K, VECTOR_CANDIDATES
from memory.store import _STOPWORDS, _WORD, MemoryStore, Turn

# Starting values (design §4, §7 decision 3), to be tuned on the memory
# evaluation's development sample.
TURN_SIMILARITY_CUTOFF = 0.5
TOP_K = 5
ANSWER_CHARS = 600
EXCERPT_STEP = 100  # how far the window over a long answer moves each time
NO_PAST_CHATS = "Nothing about this in the student's earlier chats."


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
    it mentions grades or deadlines (the memory database holds neither,
    agent memory design §5.2, cautious on purpose), or when the student had
    a memory from this turn forgotten: forgetting has to hold against this
    search too, on every later indexing pass."""
    # Old [n] numbers pointed at that answer's own searches.
    answer = _CITATION.sub("", answer)
    if (
        store.is_turn_blocked(conversation_id, turn_index)
        or mentions_grades_or_deadlines(question)
        or mentions_grades_or_deadlines(answer)
    ):
        store.delete_turn(conversation_id, turn_index)
        return False
    store.add_turn(
        conversation_id, turn_index, title=title, at=at, question=question, answer=answer,
        embedding=embed(turn_text(question, answer)),
    )
    return True


def search(
    query: str,
    *,
    store: MemoryStore,
    embed: Callable[[str], list[float]],
    now: datetime,
    k: int = TOP_K,
    skip_conversation: str | None = None,
) -> list[Turn]:
    """The k saved turns that bear most on `query`, best first. Ranked the
    way memory recall is: vector and keyword results merged by rank, only
    cosine with a threshold, then a recency weight that never drops below
    half. skip_conversation: the chat being answered, already in view."""
    vector = [
        turn
        for turn, cosine in store.turn_vector_search(embed(query), VECTOR_CANDIDATES, skip_conversation)
        if cosine >= TURN_SIMILARITY_CUTOFF
    ]
    keyword = [turn for turn, _ in store.turn_keyword_search(query, KEYWORD_CANDIDATES, skip_conversation)]

    relevance: dict[tuple[str, int], float] = {}
    by_key: dict[tuple[str, int], Turn] = {}
    for ranked in (vector, keyword):
        for rank, turn in enumerate(ranked, start=1):
            key = (turn.conversation_id, turn.turn_index)
            relevance[key] = relevance.get(key, 0.0) + 1.0 / (RRF_K + rank)
            by_key[key] = turn

    def score(key: tuple[str, int]) -> float:
        days = max((now - by_key[key].at).total_seconds() / 86400, 0.0)
        return relevance[key] * (0.5 + 0.5 * math.exp(-days / RECENCY_DAYS))

    return [by_key[key] for key in sorted(by_key, key=lambda key: -score(key))[:k]]


def excerpt(answer: str, query: str) -> str:
    """At most ANSWER_CHARS of a past answer: the stretch holding the most of
    the query's words, or its start when none match. The first 600
    characters alone hid what was asked about: in the memory evaluation the
    right chat came back 11 times in 12, and in 4 of the misses the detail
    sat further into a long answer (a name at character 1,165, an item deep
    in a list)."""
    if len(answer) <= ANSWER_CHARS:
        return answer
    words = {w for w in _WORD.findall(query.lower()) if w not in _STOPWORDS}
    lowered = answer.lower()
    last = len(answer) - ANSWER_CHARS
    best_start, best_score = 0, 0
    for start in [*range(0, last, EXCERPT_STEP), last]:
        window = lowered[start : start + ANSWER_CHARS]
        score = sum(w in window for w in words)
        if score > best_score:  # ties keep the earlier stretch
            best_start, best_score = start, score
    end = best_start + ANSWER_CHARS
    return ("…" if best_start else "") + answer[best_start:end] + ("…" if end < len(answer) else "")


def format_turns(turns: list[Turn], first_label: int = 1, query: str = "") -> str:
    """Search results as the model sees them. [P…] labels are never
    citations: chat strips them from the answer, as it does memory's [M…].
    query: what was searched for, which decides the part of a long answer shown."""
    if not turns:
        return NO_PAST_CHATS
    parts = []
    for label, turn in enumerate(turns, start=first_label):
        answer = excerpt(turn.answer, query)
        parts.append(f'[P{label}] "{turn.title}", {turn.at.date()}\nStudent: {turn.question}\nAssistant: {answer}')
    return "\n\n".join(parts)
