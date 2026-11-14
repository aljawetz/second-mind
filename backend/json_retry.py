"""One retry when a model's JSON reply can't be used (RAG gaps plan, task 4).

A provider's complete_json returns None when the reply isn't JSON, and only
the caller knows whether parsed JSON has the fields it needs. So the caller
passes `valid`, and an unusable first reply (None or not valid) gets one more
try with a reminder appended. A second failure returns None, which every
caller already treats as "nothing to do".

Errors the provider raises (network, auth) aren't retried: asking again
won't fix them, and each caller already decides what an error means.

Kept out of llm.py so the memory package can use it without importing the
OpenAI client.
"""

import logging
import threading
from typing import Callable

logger = logging.getLogger(__name__)

RETRY_NOTE = (
    "Your last reply couldn't be used: it wasn't valid JSON or didn't have the fields asked for. "
    "Return exactly one valid JSON object, in the format the instructions give, and nothing else."
)

# Since the process started (or the last reset_counts()). The memory worker
# and the evaluation's parallel runs call from several threads.
_counts = {"retried": 0, "recovered": 0, "gave_up": 0}
_lock = threading.Lock()


def complete_json(llm, messages: list[dict], *, valid: Callable[[object], bool], label: str, **kwargs) -> object:
    """llm.complete_json(messages, **kwargs), asked once more if the reply is
    None or `valid(reply)` is false. The usable reply, or None."""
    reply = llm.complete_json(messages, **kwargs)
    if reply is not None and valid(reply):
        return reply
    _count("retried")
    reply = llm.complete_json([*messages, {"role": "user", "content": RETRY_NOTE}], **kwargs)
    if reply is not None and valid(reply):
        _count("recovered")
        logger.info("JSON retry for %s: recovered", label)
        return reply
    _count("gave_up")
    logger.warning("JSON retry for %s: gave up after two unusable replies", label)
    return None


def _count(key: str) -> None:
    with _lock:
        _counts[key] += 1


def counts() -> dict[str, int]:
    """{"retried", "recovered", "gave_up"}, for the evaluation scripts to print."""
    with _lock:
        return dict(_counts)


def reset_counts() -> None:
    with _lock:
        for key in _counts:
            _counts[key] = 0
