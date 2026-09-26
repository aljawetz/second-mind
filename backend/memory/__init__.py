"""Agent memory — what Second Mind remembers about the student, as opposed to
the course index, which remembers the course. Design:
docs/superpowers/specs/2026-09-25-agent-memory-design.md.

Nothing in this package imports canvas.py, course_sync.py or main.py: it is
meant to be used by every agent (chat first, then the assignment explainer
and study artifacts), and to run on its own for the evaluation.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from memory import consolidate, extract, forget, recall
from memory.consolidate import Decision
from memory.extract import JsonLLM
from memory.forget import SweepReport
from memory.recall import Hit
from memory.store import Memory, MemoryStore


@dataclass
class ObserveResult:
    summary: str  # the conversation's summary, rewritten to include these turns
    decisions: list[Decision]
    dropped: list[tuple[str, str]]  # (text, reason) — for the evaluation's counts


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class MemoryService:
    """One course's memory, for one student. The model, the embedder and the
    clock are passed in, the way chat.answer takes its search and provider:
    tests run offline, and the evaluation can replay a dated semester."""

    def __init__(
        self,
        sm_home: Path,
        course_id: int,
        *,
        llm: JsonLLM,
        embed: Callable[[str], list[float]],
        now: Callable[[], datetime] = _utcnow,
    ):
        self._store = MemoryStore(sm_home / "courses" / str(course_id) / "memory.db")
        self._llm = llm
        self._embed = embed
        self._now = now

    def close(self) -> None:
        self._store.close()

    def __enter__(self) -> "MemoryService":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def observe(
        self,
        messages: list[dict],
        *,
        conversation_id: str,
        turn_index: int,
        summary: str = "",
        at: datetime | None = None,
    ) -> ObserveResult:
        """Extract memories from these messages and fold them into the store.
        The app passes one turn; the evaluation a whole session. `summary`
        is the conversation's summary before these messages. `at` is when
        they were said, if not now: the worker reads turns after a restart,
        and "last Tuesday" must count from when the student said it."""
        at = at or self._now()
        extraction = extract.extract(messages, at=at, summary=summary, llm=self._llm)
        decisions = [
            consolidate.consolidate(
                candidate, store=self._store, embed=self._embed, llm=self._llm, at=at,
                provenance=[(conversation_id, turn_index)],
            )
            for candidate in extraction.memories
        ]
        return ObserveResult(extraction.summary, decisions, extraction.dropped)

    def recall(self, query: str, k: int = 5, include_history: bool = False) -> list[Hit]:
        return recall.recall(
            query, store=self._store, embed=self._embed, now=self._now(), k=k, include_history=include_history
        )

    def profile_block(self) -> str:
        return recall.profile_block(self._store)

    def list(self, include_inactive: bool = False) -> list[Memory]:
        return self._store.list_memories(include_inactive)

    def forget(self, memory_ids: list[str], reason: str = "student asked to forget") -> int:
        """Hard delete (design spec §5.7): gone from the files, not just
        hidden. Unknown ids are skipped. Returns how many were deleted."""
        found = [mid for mid in memory_ids if self._store.get(mid) is not None]
        for mid in found:
            self._store.delete(mid, at=self._now(), reason=reason)
        return len(found)

    def sweep(self) -> SweepReport:
        """Archives what has gone unused for long enough (design spec §5.7),
        by this service's clock, so the evaluation can replay a semester."""
        return forget.sweep(self._store, self._now())

    def forget_conversation(self, conversation_id: str) -> int:
        """The student deleted a chat: forget what came only from it. A
        memory also said in another chat stays."""
        return self.forget(self._store.memories_only_from(conversation_id), reason="chat deleted")
