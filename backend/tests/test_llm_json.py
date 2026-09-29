"""llm.OpenAIProvider.complete_json — the non-streaming JSON call memory
extraction and consolidation use (design spec §8) — and what the same class
sends to DeepSeek. Provider HTTP endpoints are mocked with respx, so no key
or network is needed."""

import json

import httpx
import respx

import llm
import providers

COMPLETIONS = "https://api.openai.com/v1/chat/completions"
DEEPSEEK_COMPLETIONS = "https://api.deepseek.com/chat/completions"


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

    reply = llm.OpenAIProvider(providers.OPENAI, api_key="sk-test").complete_json([{"role": "user", "content": "hi"}])

    assert reply == {"memories": [], "summary": "s"}
    sent = json.loads(route.calls[0].request.content)
    assert sent["response_format"] == {"type": "json_object"}
    assert sent["temperature"] == 0
    assert not sent.get("stream")
    assert sent["messages"] == [{"role": "user", "content": "hi"}]


@respx.mock
def test_a_reply_that_is_not_json_comes_back_as_none():
    respx.post(COMPLETIONS).mock(return_value=httpx.Response(200, json=_completion("Sure! Here are the memories:")))

    assert llm.OpenAIProvider(providers.OPENAI, api_key="sk-test").complete_json([{"role": "user", "content": "hi"}]) is None


@respx.mock
def test_deepseek_json_call_goes_to_deepseek_with_thinking_off():
    route = respx.post(DEEPSEEK_COMPLETIONS).mock(return_value=httpx.Response(200, json=_completion('{"memories": []}')))

    reply = llm.OpenAIProvider(providers.DEEPSEEK, api_key="sk-test").complete_json([{"role": "user", "content": "json"}])

    assert reply == {"memories": []}
    sent = json.loads(route.calls[0].request.content)
    assert sent["model"] == "deepseek-flash"
    assert sent["response_format"] == {"type": "json_object"}
    # Thinking mode (DeepSeek's default) ignores temperature and needs its
    # reasoning passed back on every later tool-calling turn.
    assert sent["thinking"] == {"type": "disabled"}


def _sse(*chunks):
    body = "".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n"
    return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=body.encode())


def _chunk(delta, usage=None):
    return {
        "id": "c",
        "object": "chat.completion.chunk",
        "created": 0,
        "model": "deepseek-flash",
        "choices": [{"index": 0, "delta": delta, "finish_reason": None}] if delta is not None else [],
        "usage": usage,
    }


@respx.mock
def test_deepseek_stream_with_a_required_tool_call():
    route = respx.post(DEEPSEEK_COMPLETIONS).mock(
        return_value=_sse(
            _chunk({"tool_calls": [{"index": 0, "id": "call_1", "type": "function", "function": {"name": "search", "arguments": '{"q"'}}]}),
            _chunk({"tool_calls": [{"index": 0, "function": {"arguments": ': "tcp"}'}}]}),
            _chunk(None, usage={"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10}),
        )
    )
    tools = [{"type": "function", "function": {"name": "search", "parameters": {"type": "object"}}}]

    events = list(llm.OpenAIProvider(providers.DEEPSEEK, api_key="sk-test").stream_chat([{"role": "user", "content": "hi"}], tools, require_tool=True))

    end = events[-1]
    assert [(c.name, c.arguments) for c in end.tool_calls] == [("search", {"q": "tcp"})]
    assert end.usage == {"prompt_tokens": 7, "completion_tokens": 3}
    sent = json.loads(route.calls[0].request.content)
    assert sent["tool_choice"] == "required"
    assert sent["thinking"] == {"type": "disabled"}
