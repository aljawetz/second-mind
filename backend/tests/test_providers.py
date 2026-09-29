"""providers.py — which model provider answers, and the clients built for it.
Provider HTTP endpoints are mocked with respx, so no key or network is needed."""

import json

import httpx
import pytest
import respx

import config
import providers

DEEPSEEK_COMPLETIONS = "https://api.deepseek.com/chat/completions"


@pytest.fixture
def sm_home(tmp_path, monkeypatch):
    monkeypatch.setattr(providers, "SM_HOME", tmp_path)
    return tmp_path


def test_current_is_openai_when_config_names_no_provider(sm_home):
    # Everyone onboarded before DeepSeek existed has no llm_provider at all.
    assert providers.current() is providers.OPENAI


def test_current_reads_the_provider_chosen_at_onboarding(sm_home):
    config.write_config(sm_home, {"llm_provider": "deepseek"})
    assert providers.current() is providers.DEEPSEEK


def test_an_unknown_provider_is_an_error_not_a_silent_fallback(sm_home):
    config.write_config(sm_home, {"llm_provider": "nonsense"})
    with pytest.raises(RuntimeError, match="nonsense"):
        providers.current()


def test_api_key_reads_the_providers_own_keychain_item(monkeypatch):
    asked = []
    monkeypatch.setattr(providers.keyring, "get_password", lambda service, key: asked.append(key) or "sk-deepseek")
    assert providers.api_key(providers.DEEPSEEK) == "sk-deepseek"
    assert asked == ["deepseek-key"]


def test_api_key_missing_is_a_runtime_error(monkeypatch):
    monkeypatch.setattr(providers.keyring, "get_password", lambda service, key: None)
    with pytest.raises(RuntimeError, match="DeepSeek"):
        providers.api_key(providers.DEEPSEEK)


def _completion(content):
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "created": 0,
        "model": "deepseek-flash",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }


@respx.mock
def test_llama_llm_for_deepseek_calls_deepseek_with_thinking_off(sm_home, monkeypatch):
    # llama_index's own OpenAI class rejects model names it doesn't know and
    # would send a non-OpenAI model to the legacy completions endpoint.
    monkeypatch.setattr(providers.keyring, "get_password", lambda service, key: "sk-deepseek")
    config.write_config(sm_home, {"llm_provider": "deepseek"})
    route = respx.post(DEEPSEEK_COMPLETIONS).mock(return_value=httpx.Response(200, json=_completion("hello")))

    llm = providers.llama_llm()

    assert llm.metadata.is_chat_model
    assert str(llm.complete("hi")) == "hello"
    sent = json.loads(route.calls[0].request.content)
    assert sent["model"] == "deepseek-flash"
    assert sent["thinking"] == {"type": "disabled"}
