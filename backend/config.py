"""config.json (data-model.md §3) — non-sensitive, student-level settings.
First real code for this file; only `main.py`'s startup-skip check and
onboarding-completion write use it so far.

Credentials themselves are never in here — only whether Keychain has them
(credentials_status), read the same way canvas.py/generation.py already do.
"""

import json
from pathlib import Path

import keyring

CREDENTIAL_SERVICE = "com.secondmind.app"


def config_path(sm_home: Path) -> Path:
    return sm_home / "config.json"


def read_config(sm_home: Path) -> dict:
    path = config_path(sm_home)
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def write_config(sm_home: Path, data: dict) -> None:
    sm_home.mkdir(parents=True, exist_ok=True)
    config_path(sm_home).write_text(json.dumps(data, indent=2))


def normalize_canvas_base_url(raw: str) -> str:
    """Accepts whatever a student reasonably pastes during onboarding — a
    bare domain, with or without a scheme, with or without a trailing slash
    or an accidental /api/v1 — and returns just the origin (e.g.
    "https://canvas.cmu.edu"). The single canonical form both canvas.py
    (which appends /api/v1 itself) and the frontend's citation links
    (which use the origin directly) build on top of, contribution-and-
    distribution-plan.md step 2 — Second Mind was hardcoded to canvas.cmu.edu
    before this."""
    value = raw.strip().rstrip("/")
    if not value:
        return value
    if not value.startswith(("http://", "https://")):
        value = f"https://{value}"
    if value.endswith("/api/v1"):
        value = value[: -len("/api/v1")]
    return value.rstrip("/")


def credentials_status() -> dict:
    return {
        "canvas": bool(keyring.get_password(CREDENTIAL_SERVICE, "canvas-token")),
        "openai": bool(keyring.get_password(CREDENTIAL_SERVICE, "openai-key")),
    }
