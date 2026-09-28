"""Agent memory — what Second Mind remembers about the student, as opposed to
the course index, which remembers the course. Design:
docs/superpowers/specs/2026-09-25-agent-memory-design.md.

Nothing in this package imports canvas.py, course_sync.py or main.py: it is
meant to be used by every agent (chat first, then the assignment explainer
and study artifacts), and to run on its own for the evaluation.
"""

from __future__ import annotations

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
        conversation_id: str | None = None,
        on_forget: Callable[[list[str]], None] | None = None,
    ):
        """conversation_id: the chat this service answers in, if any; recall
        leaves out that chat's own summary. on_forget: called with the chats
        a hard delete touched, so the app can clear their running summaries
        (this package doesn't know how chats are stored)."""
        self._store = MemoryStore(sm_home / "courses" / str(course_id) / "memory.db")
        self._llm = llm
        self._embed = embed
        self._now = now
        self._conversation_id = conversation_id
        self._on_forget = on_forget

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
        if self._store.is_turn_blocked(conversation_id, turn_index):
            return ObserveResult(summary, [], [])
        extraction = extract.extract(messages, at=at, summary=summary, llm=self._llm)
        decisions = [
            consolidate.consolidate(
                candidate, store=self._store, embed=self._embed, llm=self._llm, at=at,
                provenance=[(conversation_id, turn_index)],
            )
            for candidate in extraction.memories
        ]
        # The chat as a whole, recallable from other chats ("what did we go
        # over about mocks last week?"), design spec §5.6.
        if extraction.summary:
            self._store.set_summary(
                conversation_id, text=extraction.summary, embedding=self._embed(extraction.summary), at=at,
                turn_index=turn_index,
            )
        return ObserveResult(extraction.summary, decisions, extraction.dropped)

    def recall(self, query: str, k: int = 5, include_history: bool = False) -> list[Hit]:
        return recall.recall(
            query, store=self._store, embed=self._embed, now=self._now(), k=k, include_history=include_history,
            skip_conversation=self._conversation_id,
        )

    def profile_block(self) -> str:
        return recall.profile_block(self._store)

    def list(self, include_inactive: bool = False) -> list[Memory]:
        return self._store.list_memories(include_inactive)

    def update_text(self, memory_id: str, text: str) -> Memory | None:
        """Student edit from Manage memories. Only current memories (active,
        not superseded or invalidated) can change."""
        memory = self._store.get(memory_id)
        if memory is None:
            return None
        if memory.status != "active" or memory.valid_to is not None:
            raise ValueError("inactive")
        text = text.strip()
        if not text:
            raise ValueError("empty")
        try:
            self._store.revise(memory_id, text=text, embedding=self._embed(text), at=self._now(), reason="student edited")
        except KeyError:
            return None
        return self._store.get(memory_id)

    def forget(self, memory_ids: list[str], reason: str = "student asked to forget") -> int:
        """Hard delete (design spec §5.7): gone from the files, not just
        hidden. Unknown ids are skipped. Returns how many were deleted.

        The summaries of the chats a memory came from go too, since they may
        repeat it, and on_forget hears which chats: their running summaries
        would otherwise write it back on the next turn."""
        found = [m for m in (self._store.get(mid) for mid in dict.fromkeys(memory_ids)) if m is not None]
        if not found:
            return 0
        for cid, turn_index in {(cid, ti) for m in found for cid, ti in m.provenance}:
            self._store.block_forget_turn(cid, turn_index)
        chats = sorted({cid for m in found for cid, _ in m.provenance} | {m.conversation_id for m in found if m.conversation_id})
        doomed = {m.id for m in found}
        doomed |= {
            m.id for m in self._store.list_memories(include_inactive=True) if m.kind == "summary" and m.conversation_id in chats
        }
        for mid in doomed:
            self._store.delete(mid, at=self._now(), reason=reason)
        if self._on_forget:
            self._on_forget(chats)
        return len(found)

    def sweep(self) -> SweepReport:
        """Archives what has gone unused for long enough (design spec §5.7),
        by this service's clock, so the evaluation can replay a semester."""
        return forget.sweep(self._store, self._now())

    def forget_conversation(self, conversation_id: str) -> int:
        """The student deleted a chat: forget what came only from it. A
        memory also said in another chat stays."""
        return self.forget(self._store.memories_only_from(conversation_id), reason="chat deleted")
