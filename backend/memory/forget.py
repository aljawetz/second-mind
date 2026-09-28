"""Forgetting by fading — design spec §5.7. A sweep archives what has gone
unused for long enough; archived memories leave recall and the profile, but
stay listed so the student can still see and delete them.

The other ways memory forgets live elsewhere: replacing and withdrawing are
consolidation's (§5.3), and a hard delete, when the student asks, is
MemoryService.forget.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from memory.recall import last_use
from memory.store import Memory, MemoryStore

# Starting values, like recall's (design spec §12).
UNUSED_DAYS = 60  # events and summaries
UNUSED_DAYS_IMPORTANT = 180  # the same, at importance 4 or 5
CLOSED_TASK_DAYS = 30


@dataclass
class SweepReport:
    archived: list[str] = field(default_factory=list)


def _rule(m: Memory, now: datetime) -> str | None:
    """Why this memory should be archived now, or None to keep it."""
    if m.kind in ("event", "summary"):
        days = UNUSED_DAYS_IMPORTANT if m.importance >= 4 else UNUSED_DAYS
        # A time still ahead ("the midterm is on Dec 10") makes this
        # negative, so it's kept until it has come and gone.
        if now - last_use(m) > timedelta(days=days):
            return f"{m.kind} unused {days}+ days"
    elif m.kind == "task":
        # Open tasks never fade: being stuck on A3 stays true until the
        # student says otherwise.
        if m.valid_to is not None and now - m.valid_to > timedelta(days=CLOSED_TASK_DAYS):
            return f"task closed {CLOSED_TASK_DAYS}+ days"
    # Facts never fade by age: only replaced, withdrawn or deleted.
    return None


def sweep(store: MemoryStore, now: datetime) -> SweepReport:
    report = SweepReport()
    for m in store.list_memories(include_inactive=True):
        if m.status != "active":
            continue
        rule = _rule(m, now)
        if rule:
            store.archive(m.id, at=now, reason=f"sweep: {rule}")
            report.archived.append(m.id)
    return report
