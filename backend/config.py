"""config.json (data-model.md §3) — non-sensitive, student-level settings.
First real code for this file; only `main.py`'s startup-skip check and
onboarding-completion write use it so far.

Credentials themselves are never in here — only whether Keychain has them
(credentials_status), read the same way canvas.py/generation.py already do.
"""

import json
from pathlib import Path

import keyring

CREDENTIAL_SERVICE = "com.ssb.app"


def config_path(ssb_home: Path) -> Path:
    return ssb_home / "config.json"


def read_config(ssb_home: Path) -> dict:
    path = config_path(ssb_home)
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def write_config(ssb_home: Path, data: dict) -> None:
    ssb_home.mkdir(parents=True, exist_ok=True)
    config_path(ssb_home).write_text(json.dumps(data, indent=2))


def credentials_status() -> dict:
    return {
        "canvas": bool(keyring.get_password(CREDENTIAL_SERVICE, "canvas-token")),
        "openai": bool(keyring.get_password(CREDENTIAL_SERVICE, "openai-key")),
    }
