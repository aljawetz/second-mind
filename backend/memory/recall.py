"""Recall — design spec §5.5. Finds the memories that bear on a question,
and presents them to the model.

Vector and keyword results are combined by rank (reciprocal rank fusion),
not by score: cosine and BM25 scores aren't on the same scale, which the
team learned from LanceDB's hybrid mode (generation.HybridRetriever). Only
cosine gets a threshold; a keyword match counts by its rank alone.
"""

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

import numpy as np

from memory.store import KINDS, Memory, MemoryStore

# Starting values, calibrated in the evaluation (design spec §12).
# Measured with the real BGE model, 12 questions against 8 memories
# (2026-10-06): related pairs score 0.58-0.76, unrelated ones up to ~0.61,
# so the first 0.5 let nearly every memory through on every question.
# Provisional until the evaluation calibrates them.
MEMORY_SIMILARITY_CUTOFF = 0.63  # meaning alone
KEYWORD_MIN_SIMILARITY = 0.5  # a keyword match needs this much meaning too ("team" -> "on team 4": 0.58)
VECTOR_CANDIDATES = 20
KEYWORD_CANDIDATES = 5
RRF_K = 60  # the usual constant: dampens the gap between rank 1 and rank 2
RECENCY_DAYS = 30

NO_MEMORIES = "Nothing about this in what the student has told you before."
PROFILE_HEADER = (
    "What the student told you in earlier conversations (their own words, summarized; not course "
    "material, never cite it):"
)
PROFILE_MAX_FACTS = 10
PROFILE_MAX_TASKS = 5
PROFILE_MAX_CHARS = 800
_FENCE_CHARS = str.maketrans("", "", "<>[]")


@dataclass
class Hit:
    memory: Memory
    score: float


def recall(
    query: str,
    *,
    store: MemoryStore,
    embed: Callable[[str], list[float]],
    now: datetime,
    k: int = 5,
    include_history: bool = False,
    skip_conversation: str | None = None,
    kinds: tuple[str, ...] = KINDS,
) -> list[Hit]:
    """The k memories that bear most on `query`, best first. Only current
    ones, unless include_history ("what was it before?"). Marks what it
    returns as used. skip_conversation: the chat being answered, whose own
    summary is left out (its history already carries it)."""

    def wanted(m: Memory) -> bool:
        return not (m.kind == "summary" and m.conversation_id == skip_conversation)

    query_vector = embed(query)
    vector = [
        m
        for m, cosine in store.vector_search(query_vector, k=VECTOR_CANDIDATES, kinds=kinds, include_history=include_history)
        if cosine >= MEMORY_SIMILARITY_CUTOFF and wanted(m)
    ]
    keyword = [
        m
        for m, _ in store.keyword_search(query, k=KEYWORD_CANDIDATES, kinds=kinds, include_history=include_history)
        if wanted(m) and _cosine(query_vector, m.embedding) >= KEYWORD_MIN_SIMILARITY
    ]

    relevance: dict[str, float] = {}
    by_id: dict[str, Memory] = {}
    for ranked in (vector, keyword):
        for rank, m in enumerate(ranked, start=1):
            relevance[m.id] = relevance.get(m.id, 0.0) + 1.0 / (RRF_K + rank)
            by_id[m.id] = m
    scored = [Hit(m, relevance[mid] * _recency(m, now) * _weight(m)) for mid, m in by_id.items()]
    hits = sorted(scored, key=lambda h: -h.score)[:k]
    # Used memories fade more slowly (design spec §5.5, §5.7).
    store.touch([h.memory.id for h in hits], at=now)
    return hits


def format_hits(hits: list[Hit], first_label: int = 1) -> str:
    """Recall results as the model sees them: "[M1] (fact, since
    2026-09-21) …". Labels continue across a turn's recalls (first_label),
    and chat maps them back to memory ids for forget_memory. Never
    citations: chat strips [M…] from the answer."""
    if not hits:
        return NO_MEMORIES
    lines = []
    for label, hit in enumerate(hits, start=first_label):
        m = hit.memory
        if m.valid_to is None:
            when = f"since {_when(m).date()}"
        else:
            ended = "replaced" if m.superseded_by else "no longer true"
            when = f"{_when(m).date()} to {m.valid_to.date()}, {ended}"
        lines.append(f"[M{label}] ({m.kind}, {when}) {_as_data(m.text)}")
    return "\n".join(lines)


def profile_block(store: MemoryStore) -> str:
    """The part of chat's system prompt that's there on every question, so
    a preference ("code examples in Java") applies without any search:
    current facts, most important first, then open tasks, newest first.
    "" when nothing is known. Not marked as used: it's shown every time."""
    current = store.list_memories()
    facts = sorted((m for m in current if m.kind == "fact"), key=lambda m: (-m.importance, -_when(m).timestamp()))
    tasks = sorted((m for m in current if m.kind == "task"), key=lambda m: -_when(m).timestamp())
    if not facts and not tasks:
        return ""

    opening, closing = f"{PROFILE_HEADER}\n<memories>", "</memories>"
    room = PROFILE_MAX_CHARS - len(opening) - len(closing) - 2
    lines: list[str] = []

    def fit(line: str) -> bool:
        nonlocal room
        if len(line) + 1 > room:
            return False
        lines.append(line)
        room -= len(line) + 1
        return True

    for m in facts[:PROFILE_MAX_FACTS]:
        if not fit(_profile_line(m)):
            break
    if tasks and fit("Open tasks:"):
        for m in tasks[:PROFILE_MAX_TASKS]:
            if not fit(_profile_line(m)):
                break
    return "\n".join([opening, *lines, closing])


def _profile_line(m: Memory) -> str:
    return f"- {_as_data(m.text)} (since {_when(m).date()})"


def _when(m: Memory) -> datetime:
    return m.event_time or m.created_at


def _cosine(a: list[float], b: list[float]) -> float:
    a, b = np.asarray(a, dtype=np.float32), np.asarray(b, dtype=np.float32)
    norms = float(np.linalg.norm(a) * np.linalg.norm(b))
    return float(a @ b) / norms if norms else 0.0


def last_use(m: Memory) -> datetime:
    """When a memory last mattered: last recalled, else when it happened or
    was said. Recency here and fading in forget.py both count from it."""
    return m.last_accessed or _when(m)


def _as_data(text: str) -> str:
    """Memory text goes into a system prompt. It's the student's own words,
    but it still mustn't be able to close the fence it sits in."""
    return text.translate(_FENCE_CHARS)


def _recency(m: Memory, now: datetime) -> float:
    """1 for facts: being on team 4 is as true in November. For events,
    tasks and summaries, 1 when just used or made, falling towards 0.5
    (never lower, so an old but exact match still comes up)."""
    if m.kind == "fact":
        return 1.0
    days = max((now - last_use(m)).total_seconds() / 86400, 0.0)
    return 0.5 + 0.5 * math.exp(-days / RECENCY_DAYS)


def _weight(m: Memory) -> float:
    """Importance 1 → 0.68, 5 → 1.0: enough to settle close calls, not
    enough to lift a poor match over a good one."""
    return 0.6 + 0.08 * m.importance
