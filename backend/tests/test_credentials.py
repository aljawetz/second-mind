"""credentials.py — launched by the app the backend must never touch the
Keychain (that's what made macOS prompt twice); on its own it still does."""

import json

import pytest

import credentials


def _keychain_must_not_be_used(*args):
    raise AssertionError("the backend touched the Keychain while launched by the app")


@pytest.fixture
def from_app(monkeypatch):
    monkeypatch.setenv(credentials.FROM_APP_ENV, "1")
    monkeypatch.setattr(credentials, "_values", {})
    monkeypatch.setattr(credentials.keyring, "get_password", _keychain_must_not_be_used)
    monkeypatch.setattr(credentials.keyring, "set_password", _keychain_must_not_be_used)


def test_on_its_own_it_reads_the_keychain(monkeypatch):
    monkeypatch.delenv(credentials.FROM_APP_ENV, raising=False)
    monkeypatch.setattr(credentials.keyring, "get_password", lambda service, key: f"{service}/{key}")
    assert credentials.get("canvas-token") == "com.secondmind.app/canvas-token"


def test_on_its_own_it_writes_the_keychain(monkeypatch):
    monkeypatch.delenv(credentials.FROM_APP_ENV, raising=False)
    saved = {}
    monkeypatch.setattr(credentials.keyring, "set_password", lambda service, key, value: saved.__setitem__((service, key), value))
    credentials.store("github-copilot-token", "gho_x")
    assert saved == {("com.secondmind.app", "github-copilot-token"): "gho_x"}


def test_from_the_app_it_reads_what_the_app_sent(from_app):
    credentials.receive(b'{"canvas-token": "t", "openai-key": "sk-a"}\n')
    credentials.receive(b'{"openai-key": "sk-b"}\n')
    assert credentials.get("canvas-token") == "t"
    assert credentials.get("openai-key") == "sk-b"
    assert credentials.get("deepseek-key") is None


def test_from_the_app_a_malformed_line_changes_nothing(from_app):
    credentials.receive(b'{"canvas-token": "t"}\n')
    for line in (b"", b"not json\n", b'["canvas-token"]\n', b'{"canvas-token": 5}\n'):
        credentials.receive(line)
    assert credentials.get("canvas-token") == "t"


def test_from_the_app_storing_hands_the_value_to_the_app(from_app, capsys):
    credentials.store("github-copilot-token", "gho_x")
    assert credentials.get("github-copilot-token") == "gho_x"
    out = capsys.readouterr().out
    assert out.startswith(credentials.SAVE_PREFIX) and out.endswith("\n")
    assert json.loads(out[len(credentials.SAVE_PREFIX) :]) == {"github-copilot-token": "gho_x"}
