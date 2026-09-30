"""github_signin.py — "Sign in with GitHub" for the Copilot provider (OAuth
device flow). GitHub's endpoints are mocked with respx and the Keychain is
faked, so no network, no account."""

import httpx
import pytest
import respx

import github_signin
import providers

DEVICE_CODE = "https://github.com/login/device/code"
TOKEN = "https://github.com/login/oauth/access_token"
USER = "https://api.github.com/user"


@pytest.fixture(autouse=True)
def app(monkeypatch):
    monkeypatch.setattr(github_signin, "CLIENT_ID", "Ov23test")
    monkeypatch.setattr(github_signin, "_pending", None)
    stored = {}
    monkeypatch.setattr(github_signin.keyring, "set_password", lambda service, key, value: stored.__setitem__(key, value))
    return stored


def _start():
    respx.post(DEVICE_CODE).mock(
        return_value=httpx.Response(
            200,
            json={
                "device_code": "dev-123",
                "user_code": "ABCD-1234",
                "verification_uri": "https://github.com/login/device",
                "expires_in": 900,
                "interval": 5,
            },
        )
    )
    return github_signin.start()


@respx.mock
def test_start_returns_the_code_to_show_but_keeps_the_device_code():
    shown = _start()
    assert shown == {"user_code": "ABCD-1234", "verification_uri": "https://github.com/login/device", "interval": 5, "expires_in": 900}
    sent = respx.calls[0].request
    assert b"client_id=Ov23test" in sent.content
    assert b"scope=read%3Auser" in sent.content


def test_start_without_a_client_id_says_sign_in_isnt_set_up(monkeypatch):
    monkeypatch.setattr(github_signin, "CLIENT_ID", "")
    with pytest.raises(github_signin.SignInError, match="isn't set up"):
        github_signin.start()


@respx.mock
def test_poll_before_approval_is_pending():
    _start()
    respx.post(TOKEN).mock(return_value=httpx.Response(200, json={"error": "authorization_pending"}))
    assert github_signin.poll() == {"status": "pending"}


@respx.mock
def test_slow_down_passes_on_the_new_interval():
    _start()
    respx.post(TOKEN).mock(return_value=httpx.Response(200, json={"error": "slow_down", "interval": 10}))
    assert github_signin.poll() == {"status": "pending", "interval": 10}


@respx.mock
def test_approval_stores_the_token_as_the_copilot_credential(app):
    _start()
    token_route = respx.post(TOKEN).mock(return_value=httpx.Response(200, json={"access_token": "gho_abc", "token_type": "bearer"}))
    respx.get(USER).mock(return_value=httpx.Response(200, json={"login": "yongjies-cmu-S26"}))

    assert github_signin.poll() == {"status": "done", "login": "yongjies-cmu-S26"}
    assert app == {providers.COPILOT.credential: "gho_abc"}
    assert b"device_code=dev-123" in token_route.calls[0].request.content
    # Done: a second poll has nothing left to ask about.
    assert github_signin.poll() == {"status": "expired"}


@respx.mock
def test_a_failed_login_lookup_still_signs_in(app):
    _start()
    respx.post(TOKEN).mock(return_value=httpx.Response(200, json={"access_token": "gho_abc"}))
    respx.get(USER).mock(return_value=httpx.Response(500))
    assert github_signin.poll() == {"status": "done", "login": None}
    assert app


@respx.mock
@pytest.mark.parametrize("error, status", [("access_denied", "denied"), ("expired_token", "expired")])
def test_denied_or_expired_ends_the_flow(error, status):
    _start()
    respx.post(TOKEN).mock(return_value=httpx.Response(200, json={"error": error}))
    assert github_signin.poll() == {"status": status}
    assert github_signin.poll() == {"status": "expired"}


def test_poll_with_nothing_started_is_expired():
    assert github_signin.poll() == {"status": "expired"}


@respx.mock
def test_github_unreachable_is_an_error_not_a_crash():
    _start()
    respx.post(TOKEN).mock(side_effect=httpx.ConnectError("offline"))
    result = github_signin.poll()
    assert result["status"] == "error"


def test_endpoints_through_the_real_handler(monkeypatch):
    import http.client
    import json
    import threading

    import main

    monkeypatch.setattr(github_signin, "CLIENT_ID", "")
    server = main.ThreadingHTTPServer(("127.0.0.1", 0), main.Handler)
    threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
    try:
        conn = http.client.HTTPConnection("127.0.0.1", server.server_address[1])
        conn.request("POST", "/github/device/start", body=b"{}")
        response = conn.getresponse()
        assert response.status == 503
        assert json.loads(response.read())["error"]["code"] == "github_signin_unavailable"
        conn.request("POST", "/github/device/poll", body=b"{}")
        response = conn.getresponse()
        assert json.loads(response.read()) == {"status": "expired"}
    finally:
        server.shutdown()
        server.server_close()
