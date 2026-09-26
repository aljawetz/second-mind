"""Feeds saved course chats (conversations.py) to agent memory (memory/) —
docs/superpowers/specs/2026-09-25-agent-memory-design.md §5.1.

Here rather than in memory/, which knows nothing about how the app stores
chats: that package is meant for every agent, and for the evaluation.
"""

import threading
from datetime import datetime
from pathlib import Path

import conversations
from embeddings import OnnxBgeEmbedding
from memory import MemoryService

_embedder: OnnxBgeEmbedding | None = None
_embedder_lock = threading.Lock()


def embed(text: str) -> list[float]:
    """The same local BGE model as course search, loaded once and shared by
    request threads and the memory worker."""
    global _embedder
    with _embedder_lock:
        if _embedder is None:
            _embedder = OnnxBgeEmbedding()
    return _embedder.get_text_embedding(text)


def observe_conversation(sm_home: Path, course_id: int, cid: str, service: MemoryService) -> int:
    """Reads the turns of this chat memory hasn't read yet, one turn per
    call, each dated when it was asked. Progress is saved after every turn,
    so a failure repeats at most that turn. Returns how many were read."""
    c = conversations.get_conversation(sm_home, course_id, cid)
    if c is None:
        return 0
    start, summary = c["memory_processed_upto"], c["summary"]
    turns = c["turns"][start:]
    for index, turn in enumerate(turns, start=start):
        messages = [{"role": "user", "content": turn["question"]}, {"role": "assistant", "content": turn["answer"]}]
        result = service.observe(
            messages,
            conversation_id=cid,
            turn_index=index,
            summary=summary,
            at=datetime.fromisoformat(turn["asked_at"]),
        )
        summary = result.summary
        conversations.set_memory_progress(sm_home, course_id, cid, processed_upto=index + 1, summary=summary)
        # Deleted while this turn was being read: the delete's own cascade
        # may already have run, so forget what this turn added.
        if not conversations.exists(sm_home, course_id, cid):
            service.forget_conversation(cid)
            return index + 1 - start
    return len(turns)


def pending(sm_home: Path, course_ids: list[int]) -> list[tuple[int, str]]:
    """(course, chat) pairs with turns memory hasn't read: queued again at
    startup, so turns left over from a quit aren't lost."""
    return [(course_id, cid) for course_id in course_ids for cid in conversations.pending_memory(sm_home, course_id)]
