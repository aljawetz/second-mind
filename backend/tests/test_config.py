"""config.py — real filesystem I/O against a temp dir, no fixtures needed."""

from pathlib import Path

import config


def test_read_config_missing_file_returns_empty_dict(tmp_path: Path):
    assert config.read_config(tmp_path) == {}


def test_write_then_read_round_trips(tmp_path: Path):
    data = {"selected_courses": [55710], "llm_provider": "openai", "onboarding_complete": True}
    config.write_config(tmp_path, data)
    assert config.read_config(tmp_path) == data


def test_write_creates_ssb_home_if_missing(tmp_path: Path):
    ssb_home = tmp_path / "not_yet_created"
    config.write_config(ssb_home, {"onboarding_complete": True})
    assert (ssb_home / "config.json").exists()


def test_credentials_status_reports_missing_when_no_keyring_entry(monkeypatch):
    monkeypatch.setattr(config.keyring, "get_password", lambda service, key: None)
    assert config.credentials_status() == {"canvas": False, "openai": False}


def test_credentials_status_reports_present(monkeypatch):
    monkeypatch.setattr(config.keyring, "get_password", lambda service, key: "some-value")
    assert config.credentials_status() == {"canvas": True, "openai": True}
