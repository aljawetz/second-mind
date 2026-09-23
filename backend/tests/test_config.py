"""config.py — real filesystem I/O against a temp dir, no fixtures needed."""

from pathlib import Path

import config


def test_read_config_missing_file_returns_empty_dict(tmp_path: Path):
    assert config.read_config(tmp_path) == {}


def test_write_then_read_round_trips(tmp_path: Path):
    data = {"selected_courses": [55710], "llm_provider": "openai", "onboarding_complete": True}
    config.write_config(tmp_path, data)
    assert config.read_config(tmp_path) == data


def test_write_creates_sm_home_if_missing(tmp_path: Path):
    sm_home = tmp_path / "not_yet_created"
    config.write_config(sm_home, {"onboarding_complete": True})
    assert (sm_home / "config.json").exists()


def test_credentials_status_reports_missing_when_no_keyring_entry(monkeypatch):
    monkeypatch.setattr(config.keyring, "get_password", lambda service, key: None)
    assert config.credentials_status() == {"canvas": False, "openai": False}


def test_credentials_status_reports_present(monkeypatch):
    monkeypatch.setattr(config.keyring, "get_password", lambda service, key: "some-value")
    assert config.credentials_status() == {"canvas": True, "openai": True}


def test_normalize_canvas_base_url_adds_scheme():
    assert config.normalize_canvas_base_url("canvas.cmu.edu") == "https://canvas.cmu.edu"


def test_normalize_canvas_base_url_strips_trailing_slash():
    assert config.normalize_canvas_base_url("https://canvas.cmu.edu/") == "https://canvas.cmu.edu"


def test_normalize_canvas_base_url_strips_pasted_api_path():
    assert config.normalize_canvas_base_url("https://canvas.cmu.edu/api/v1") == "https://canvas.cmu.edu"


def test_normalize_canvas_base_url_keeps_explicit_http():
    assert config.normalize_canvas_base_url("http://localhost:8080") == "http://localhost:8080"


def test_normalize_canvas_base_url_empty_stays_empty():
    assert config.normalize_canvas_base_url("   ") == ""


# --- SSB → Second Mind data-folder migration ---------------------------------


def test_migrate_legacy_home_moves_the_old_folder(tmp_path):
    legacy, new = tmp_path / ".ssb", tmp_path / ".secondmind"
    (legacy / "index.lancedb").mkdir(parents=True)
    assert config.migrate_legacy_home(new, legacy) is True
    assert not legacy.exists() and (new / "index.lancedb").is_dir()


def test_migrate_legacy_home_never_touches_an_existing_new_folder(tmp_path):
    legacy, new = tmp_path / ".ssb", tmp_path / ".secondmind"
    legacy.mkdir(); (legacy / "config.json").write_text("old")
    new.mkdir(); (new / "config.json").write_text("new")
    assert config.migrate_legacy_home(new, legacy) is False
    assert (new / "config.json").read_text() == "new" and (legacy / "config.json").read_text() == "old"


def test_migrate_legacy_home_is_a_no_op_on_a_fresh_install(tmp_path):
    assert config.migrate_legacy_home(tmp_path / ".secondmind", tmp_path / ".ssb") is False
    assert not (tmp_path / ".secondmind").exists()
