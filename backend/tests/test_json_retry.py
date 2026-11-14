"""json_retry.complete_json — one retry when a model's JSON reply is unusable
(RAG gaps plan, task 4). A scripted model stands in for the provider."""

import logging

import pytest

import json_retry

MESSAGES = [{"role": "system", "content": "Reply with JSON."}, {"role": "user", "content": "hi"}]


def has_items(reply):
    return isinstance(reply, dict) and isinstance(reply.get("items"), list)


class ScriptedLLM:
    def __init__(self, *replies):
        self._replies = list(replies)
        self.calls = []

    def complete_json(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        reply = self._replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


@pytest.fixture(autouse=True)
def fresh_counts():
    json_retry.reset_counts()
    yield
    json_retry.reset_counts()


def test_a_usable_first_reply_is_returned_without_a_retry():
    llm = ScriptedLLM({"items": [1]})

    assert json_retry.complete_json(llm, MESSAGES, valid=has_items, label="t") == {"items": [1]}
    assert len(llm.calls) == 1
    assert llm.calls[0][0] == MESSAGES
    assert json_retry.counts() == {"retried": 0, "recovered": 0, "gave_up": 0}


def test_a_reply_that_is_not_json_is_retried_once_and_the_second_reply_used():
    llm = ScriptedLLM(None, {"items": []})

    assert json_retry.complete_json(llm, MESSAGES, valid=has_items, label="t") == {"items": []}
    assert len(llm.calls) == 2
    retry_messages = llm.calls[1][0]
    assert retry_messages[: len(MESSAGES)] == MESSAGES
    assert retry_messages[-1]["role"] == "user"
    assert "Return exactly one valid JSON object" in retry_messages[-1]["content"]
    assert json_retry.counts() == {"retried": 1, "recovered": 1, "gave_up": 0}


def test_json_of_the_wrong_shape_is_retried_too():
    llm = ScriptedLLM({"memories": "oops"}, {"items": [2]})

    assert json_retry.complete_json(llm, MESSAGES, valid=has_items, label="t") == {"items": [2]}
    assert len(llm.calls) == 2


def test_after_two_unusable_replies_it_gives_up_with_none():
    llm = ScriptedLLM(None, ["not", "an", "object"])

    assert json_retry.complete_json(llm, MESSAGES, valid=has_items, label="t") is None
    assert len(llm.calls) == 2
    assert json_retry.counts() == {"retried": 1, "recovered": 0, "gave_up": 1}


def test_the_callers_messages_are_not_changed():
    llm = ScriptedLLM(None, {"items": []})
    messages = [dict(m) for m in MESSAGES]

    json_retry.complete_json(llm, messages, valid=has_items, label="t")

    assert messages == MESSAGES


def test_keyword_arguments_reach_both_calls():
    llm = ScriptedLLM(None, {"items": []})

    json_retry.complete_json(llm, MESSAGES, valid=has_items, label="t", temperature=0.7)

    assert [kwargs for _, kwargs in llm.calls] == [{"temperature": 0.7}, {"temperature": 0.7}]


def test_a_provider_error_is_not_retried():
    # A network or auth failure isn't a bad reply: asking again won't fix it,
    # and the caller already decides what an error means.
    llm = ScriptedLLM(RuntimeError("down"), {"items": []})

    with pytest.raises(RuntimeError):
        json_retry.complete_json(llm, MESSAGES, valid=has_items, label="t")
    assert len(llm.calls) == 1
    assert json_retry.counts()["retried"] == 0


def test_each_retry_is_logged_with_its_label_and_outcome(caplog):
    caplog.set_level(logging.INFO, logger="json_retry")

    json_retry.complete_json(ScriptedLLM(None, {"items": []}), MESSAGES, valid=has_items, label="memory.extract")
    json_retry.complete_json(ScriptedLLM(None, None), MESSAGES, valid=has_items, label="study.check")

    text = caplog.text
    assert "memory.extract" in text and "recovered" in text
    assert "study.check" in text and "gave up" in text
