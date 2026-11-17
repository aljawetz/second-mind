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


# verify_credential: the format check, then one real call (found in the
# Sprint 9 test run: any 20 characters passed as a Canvas token).

CANVAS_TOKEN = "1234~" + "a" * 40
OPENAI_KEY = "sk-" + "a" * 40


def _canvas_answers(monkeypatch, status=None, error=None):
    seen = {}

    def fake_get(url, headers, timeout):
        seen["url"], seen["auth"] = url, headers["Authorization"]
        if error:
            raise error
        return httpx.Response(status, request=httpx.Request("GET", url))

    monkeypatch.setattr(main.httpx, "get", fake_get)
    return seen


def test_a_canvas_token_canvas_accepts_is_valid(monkeypatch):
    seen = _canvas_answers(monkeypatch, 200)
    assert main.verify_credential("canvas", CANVAS_TOKEN, "canvas.example.edu/") == (True, "")
    assert seen == {"url": "https://canvas.example.edu/api/v1/users/self", "auth": f"Bearer {CANVAS_TOKEN}"}


def test_a_canvas_token_canvas_rejects_is_invalid(monkeypatch):
    _canvas_answers(monkeypatch, 401)
    valid, reason = main.verify_credential("canvas", CANVAS_TOKEN, "https://canvas.example.edu")
    assert not valid and "didn't accept" in reason


def test_an_unreachable_canvas_url_is_invalid(monkeypatch):
    _canvas_answers(monkeypatch, error=httpx.ConnectError("no route"))
    valid, reason = main.verify_credential("canvas", CANVAS_TOKEN, "https://not-canvas.example")
    assert not valid and "couldn't reach Canvas" in reason


def test_a_badly_formed_canvas_token_is_refused_without_calling_canvas(monkeypatch):
    seen = _canvas_answers(monkeypatch, 200)
    valid, _ = main.verify_credential("canvas", "short", "https://canvas.example.edu")
    assert not valid and seen == {}


def test_without_a_canvas_url_only_the_format_is_checked(monkeypatch):
    seen = _canvas_answers(monkeypatch, 401)
    assert main.verify_credential("canvas", CANVAS_TOKEN) == (True, "")
    assert seen == {}


class _FakeModels:
    def __init__(self, error):
        self.error = error

    def list(self):
        if self.error:
            raise self.error
        return []


class _FakeClient:
    def __init__(self, error=None):
        self.models = _FakeModels(error)

    def with_options(self, **kwargs):
        return self


@pytest.mark.parametrize(
    "error, expected_valid, reason_part",
    [
        (None, True, ""),
        (openai.AuthenticationError("bad key", response=httpx.Response(401, request=httpx.Request("GET", "https://x")), body=None), False, "didn't accept"),
        (openai.APIConnectionError(request=httpx.Request("GET", "https://x")), False, "couldn't reach"),
        (_status_error(429), True, ""),
    ],
)
def test_a_model_key_is_checked_with_the_provider(monkeypatch, error, expected_valid, reason_part):
    monkeypatch.setattr(providers, "openai_client", lambda provider, key: _FakeClient(error))
    valid, reason = main.verify_credential("openai", OPENAI_KEY)
    assert valid is expected_valid and reason_part in reason


def test_a_copilot_token_keeps_the_format_check_only(monkeypatch):
    monkeypatch.setattr(providers, "openai_client", lambda provider, key: pytest.fail("no call expected"))
    assert main.verify_credential("copilot", "github_pat_" + "a" * 40) == (True, "")
