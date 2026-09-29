"""The student's secrets — Canvas token and model-provider keys — as the
backend sees them.

Launched by the app, the backend never touches the macOS Keychain: the
Tauri app (lib.rs) is the only process that reads or writes it. Two
programs reading the same items meant two sets of Keychain prompts, and
"Always Allow" for an ad-hoc signed program only lasts until it's rebuilt.
Instead the app sends every stored credential on stdin as one JSON line
({key: value, ...}) before anything else, then another line each time one
changes; this process keeps them in memory. What the backend itself
obtains (Sign in with GitHub's token) goes back to the app as a stdout line
starting with SAVE_PREFIX, which the app saves to the Keychain and keeps
out of its log.

Run on its own (tests, scripts, `python main.py` in dev) nothing comes on
stdin, so it reads and writes the Keychain directly instead.
"""

import json
import os
import sys
import threading

import keyring

SERVICE = "com.secondmind.app"
FROM_APP_ENV = "SM_CREDENTIALS_ON_STDIN"
SAVE_PREFIX = "sm-credential:"

_values: dict[str, str] = {}
_lock = threading.Lock()


def from_app() -> bool:
    return os.environ.get(FROM_APP_ENV) == "1"


def get(key: str) -> str | None:
    if not from_app():
        return keyring.get_password(SERVICE, key)
    with _lock:
        return _values.get(key)


def store(key: str, value: str) -> None:
    if not from_app():
        keyring.set_password(SERVICE, key, value)
        return
    with _lock:
        _values[key] = value
    # One write call, so another thread's print can't land mid-line.
    sys.stdout.write(SAVE_PREFIX + json.dumps({key: value}) + "\n")
    sys.stdout.flush()


def receive(line: bytes) -> None:
    """One line from the app; anything that isn't {str: str} is ignored."""
    try:
        update = json.loads(line)
    except ValueError:
        return
    if not isinstance(update, dict):
        return
    with _lock:
        _values.update({k: v for k, v in update.items() if isinstance(k, str) and isinstance(v, str)})
