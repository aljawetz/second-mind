"""scripts/eval_key.py: evaluation scripts spend on a key of their own
(Keychain item "openai-eval-key") when one is stored, not the app's."""

import importlib.util
import sys
from pathlib import Path

import pytest

import credentials
import providers

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "eval_key.py"


@pytest.fixture
def eval_key(monkeypatch):
    spec = importlib.util.spec_from_file_location("eval_key", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(credentials, "get", credentials.get)  # restored after each test
    return module


def _stored(monkeypatch, values):
    monkeypatch.setattr(credentials, "get", lambda key: values.get(key))


def test_the_eval_key_is_used_for_openai_when_one_is_stored(eval_key, monkeypatch):
    _stored(monkeypatch, {"openai-key": "sk-app", "openai-eval-key": "sk-eval"})
    assert eval_key.use_eval_key() is True
    assert providers.api_key(providers.OPENAI) == "sk-eval"


def test_without_an_eval_key_the_apps_key_is_used(eval_key, monkeypatch):
    _stored(monkeypatch, {"openai-key": "sk-app"})
    assert eval_key.use_eval_key() is False
    assert providers.api_key(providers.OPENAI) == "sk-app"


def test_other_credentials_are_left_alone(eval_key, monkeypatch):
    _stored(monkeypatch, {"openai-key": "sk-app", "openai-eval-key": "sk-eval", "canvas-token": "c", "deepseek-key": "d"})
    eval_key.use_eval_key()
    assert credentials.get("canvas-token") == "c"
    assert credentials.get("deepseek-key") == "d"
