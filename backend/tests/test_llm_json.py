"""llm.OpenAIProvider.complete_json — the non-streaming JSON call memory
extraction and consolidation use (design spec §8). OpenAI's HTTP endpoint
is mocked with respx, so no key or network is needed."""

import json

import httpx
import respx

import llm

COMPLETIONS = "https://api.openai.com/v1/chat/completions"


def _completion(content):
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "created": 0,
        "model": "gpt-4o-mini",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }


@respx.mock
def test_complete_json_asks_for_json_at_temperature_zero_and_parses_the_reply():
    route = respx.post(COMPLETIONS).mock(return_value=httpx.Response(200, json=_completion('{"memories": [], "summary": "s"}')))

    reply = llm.OpenAIProvider(api_key="sk-test").complete_json([{"role": "user", "content": "hi"}])

    assert reply == {"memories": [], "summary": "s"}
    sent = json.loads(route.calls[0].request.content)
    assert sent["response_format"] == {"type": "json_object"}
    assert sent["temperature"] == 0
    assert not sent.get("stream")
    assert sent["messages"] == [{"role": "user", "content": "hi"}]


@respx.mock
def test_a_reply_that_is_not_json_comes_back_as_none():
    respx.post(COMPLETIONS).mock(return_value=httpx.Response(200, json=_completion("Sure! Here are the memories:")))

    assert llm.OpenAIProvider(api_key="sk-test").complete_json([{"role": "user", "content": "hi"}]) is None
