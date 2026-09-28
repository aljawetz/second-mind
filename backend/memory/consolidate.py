"""Consolidation — design spec §5.3. Each candidate from extraction is
compared with the stored memories it resembles, and the model decides
whether it's new (ADD), replaces one (UPDATE), takes one back
(INVALIDATE), or is already known (NOOP).

Most candidates resemble nothing and are added with no model call at all:
only similar memories of the same kind are worth the comparison.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from memory.extract import Candidate, JsonLLM
from memory.store import MemoryStore

# Starting value, calibrated in the evaluation (design spec §12): below it,
# two memories are about different things and the model isn't asked.
CONSOLIDATE_SIMILARITY = 0.70
MAX_NEIGHBOURS = 5

SYSTEM_PROMPT = """You maintain Second Mind's memory of one student. A new memory has just \
been taken from a conversation. Compare it with the stored memories that look similar, and decide \
what to do:
- ADD: it's new information; keep it alongside them.
- UPDATE n: it replaces memory n, because the same thing has changed or moved on ("switched to \
the fraud project" replaces "does the recommender project"; "finished Assignment 3" replaces \
"stuck on Assignment 3").
- INVALIDATE n: the student took memory n back and nothing replaces it ("I'm not on a team any \
more").
- NOOP n: memory n already says the same thing.
Memories about different things (a different assignment, a different person) are not the same \
thing however alike they sound: choose ADD.

Reply with JSON only: {"decision": "ADD" | "UPDATE" | "INVALIDATE" | "NOOP", "target": n or null}"""


@dataclass
class Decision:
    action: str  # ADD | UPDATE | INVALIDATE | NOOP
    memory_id: str | None  # the memory added (ADD, UPDATE); None otherwise


def consolidate(
    candidate: Candidate,
    *,
    store: MemoryStore,
    embed: Callable[[str], list[float]],
    llm: JsonLLM,
    at: datetime,
    provenance: list[tuple[str, int]],
) -> Decision:
    embedding = embed(candidate.text)
    neighbours = [
        m
        for m, score in store.vector_search(embedding, k=MAX_NEIGHBOURS, kinds=(candidate.kind,))
        if score >= CONSOLIDATE_SIMILARITY
    ]
    def add(reason: str) -> str:
        return store.add(
            kind=candidate.kind,
            text=candidate.text,
            importance=candidate.importance,
            embedding=embedding,
            created_at=at,
            event_time=candidate.event_time,
            entities=candidate.entities,
            provenance=provenance,
            reason=reason,
        )

    if not neighbours:
        return Decision("ADD", add("new"))
    reply = llm.complete_json(
        [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": _prompt(candidate, neighbours, at)}]
    )
    action, target = _parse(reply, len(neighbours))
    if action is None:
        # A duplicate can be cleaned up later; a lost fact can't be recovered.
        return Decision("ADD", add("consolidation: fallback"))

    reason = f"consolidation: {action}"
    if action == "ADD":
        return Decision("ADD", add(reason))
    old = neighbours[target - 1]
    # The old memory stopped being true when the new one started to be.
    ends = candidate.event_time or at
    if action == "UPDATE":
        new_id = add(reason)
        store.supersede(old.id, by=new_id, valid_to=ends, reason=reason)
        return Decision("UPDATE", new_id)
    if action == "INVALIDATE":
        store.invalidate(old.id, valid_to=ends, reason=reason)
    else:  # NOOP
        store.bump_importance(old.id, at=at, reason=reason)
        store.add_provenance(old.id, provenance)
    return Decision(action, None)


def _parse(reply, neighbour_count: int) -> tuple[str | None, int | None]:
    """(action, 1-based target), or (None, None) if the reply can't be used:
    an unknown decision, or a target that isn't one of the numbers shown."""
    if not isinstance(reply, dict):
        return None, None
    action = reply.get("decision")
    if action == "ADD":
        return "ADD", None
    target = reply.get("target")
    valid_target = isinstance(target, int) and not isinstance(target, bool) and 1 <= target <= neighbour_count
    if action in ("UPDATE", "INVALIDATE", "NOOP") and valid_target:
        return action, target
    return None, None


def _prompt(candidate: Candidate, neighbours: list, at: datetime) -> str:
    lines = [f"New memory ({candidate.kind}, {(candidate.event_time or at).date()}): {candidate.text}", "", "Stored memories:"]
    for n, m in enumerate(neighbours, start=1):
        lines.append(f"{n}. ({m.kind}, since {(m.event_time or m.created_at).date()}) {m.text}")
    return "\n".join(lines)
