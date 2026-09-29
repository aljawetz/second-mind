"""main.py's credential format check and how LLM failures become HTTP
errors, for each provider. No network: the errors are built by hand."""

import httpx
import openai
import pytest

import main
import providers


@pytest.fixture
def deepseek(tmp_path, monkeypatch):
    monkeypatch.setattr(providers, "SM_HOME", tmp_path)
    main.config.write_config(tmp_path, {"llm_provider": "deepseek"})


def _status_error(status, body=None):
    response = httpx.Response(status, request=httpx.Request("POST", "https://api.deepseek.com/chat/completions"))
    return openai.APIStatusError("error", response=response, body=body)


def test_deepseek_keys_are_format_checked_like_openai_keys():
    assert main.validate_credential("deepseek", "sk-" + "a" * 32) == (True, "")
    valid, reason = main.validate_credential("deepseek", "not-a-key-at-all-but-long")
    assert not valid and "DeepSeek" in reason


def test_auth_failure_names_the_chosen_provider(deepseek):
    e = openai.AuthenticationError("bad key", response=_status_error(401).response, body=None)
    status, body = main.Handler._llm_error(None, e)
    assert status == 401
    assert body["error"]["code"] == "llm_auth_failed"
    assert "DeepSeek" in body["error"]["message"]


def test_deepseek_insufficient_balance_is_quota_exceeded(deepseek):
    # DeepSeek answers an empty balance with 402, which the openai SDK
    # raises as a plain APIStatusError, not RateLimitError.
    status, body = main.Handler._llm_error(None, _status_error(402))
    assert status == 402
    assert body["error"]["code"] == "llm_quota_exceeded"
    assert "DeepSeek" in body["error"]["message"]


def test_other_provider_http_errors_are_a_bad_gateway(deepseek):
    status, body = main.Handler._llm_error(None, _status_error(400))
    assert status == 502
    assert body["error"]["code"] == "llm_error"


@pytest.mark.parametrize("token", ["github_pat_" + "a" * 40, "gho_" + "a" * 36, "ghu_" + "a" * 36])
def test_copilot_accepts_fine_grained_and_oauth_tokens(token):
    assert main.validate_credential("copilot", token) == (True, "")


def test_copilot_rejects_classic_tokens_with_a_way_forward():
    valid, reason = main.validate_credential("copilot", "ghp_" + "a" * 36)
    assert not valid
    assert "fine-grained" in reason and "Copilot Requests" in reason


@pytest.fixture
def copilot(tmp_path, monkeypatch):
    monkeypatch.setattr(providers, "SM_HOME", tmp_path)
    main.config.write_config(tmp_path, {"llm_provider": "copilot"})


@pytest.mark.parametrize(
    "status, http, code",
    [(401, 401, "llm_auth_failed"), (402, 402, "llm_quota_exceeded"), (429, 429, "llm_rate_limited"), (503, 503, "llm_unreachable"), (502, 502, "llm_error")],
)
def test_copilot_errors_map_like_the_others(copilot, status, http, code):
    e = providers.CopilotError(status, "details")
    assert isinstance(e, main.LLM_ERRORS)
    got_status, body = main.Handler._llm_error(None, e)
    assert (got_status, body["error"]["code"]) == (http, code)


def test_a_token_missing_the_copilot_permission_says_so(copilot):
    # GitHub's real answer, seen with a fine-grained token created without it.
    e = providers.CopilotError(401, 'unauthorized: Personal Access Token does not have "Copilot Requests" permission')
    status, body = main.Handler._llm_error(None, e)
    assert status == 401
    assert "Copilot Requests" in body["error"]["message"]
