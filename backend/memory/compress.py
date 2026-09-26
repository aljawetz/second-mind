"""Compression — design spec §5.6. A long conversation reaches the model as
its running summary plus the last few turns word for word, instead of a
fixed window that silently drops everything older.

The summary is extraction's (extract.py rewrites it with every turn it
reads), so it only exists as far as the memory worker has got. Where it
doesn't cover every older turn yet, or memory is off, the caller gets the
plain chat back and chat.py's usual window applies.
"""

from dataclasses import dataclass

RECENT_TURNS = 4

SUMMARY_HEADER = (
    "Earlier in this conversation, summarized (the most recent turns follow as messages; this is the "
    "conversation, not course material, so never cite it):"
)
_FENCE_CHARS = str.maketrans("", "", "<>")


@dataclass
class History:
    summary: str  # "" when the turns are sent as they are
    turns: list[dict]


def build_history(turns: list[dict], summary: str, summary_upto: int) -> History:
    """turns: the chat so far, oldest first. `summary` covers the first
    `summary_upto` of them."""
    older = len(turns) - RECENT_TURNS
    if older <= 0:
        return History("", turns)
    if summary and summary_upto >= older:
        return History(summary, turns[-RECENT_TURNS:])
    return History("", turns)


def summary_block(summary: str) -> str:
    """The summary as it goes into chat's system prompt. Model-written, from
    the student's words, so fenced like the memory profile."""
    if not summary:
        return ""
    return f"{SUMMARY_HEADER}\n<summary>\n{summary.translate(_FENCE_CHARS)}\n</summary>"
