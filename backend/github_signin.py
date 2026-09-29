"""Sign in with GitHub for the Copilot provider — GitHub's OAuth device flow,
so a student doesn't have to create a fine-grained token by hand.

The app shows a short code, the student approves it at
github.com/login/device, and the resulting OAuth token (gho_…) goes straight
into the Keychain as the Copilot credential — the webview only ever sees the
code. Copilot bills that student's own plan (copilot_llm.py).

CLIENT_ID is Second Mind's OAuth App (GitHub → Settings → Developer
settings → OAuth Apps, with "Enable Device Flow" ticked). It's public by
design: device flow uses no client secret.

One flow at a time — one student per machine — kept in memory: the
device_code never leaves the backend.
"""

import threading
import time

import httpx
import keyring

import config
import providers

CLIENT_ID = "Ov23linVKlGHPXSemOp0"
# The Copilot SDK's own sample asks for read:user; Copilot itself needs no
# scope, only the account's Copilot plan.
SCOPE = "read:user"

DEVICE_CODE_URL = "https://github.com/login/device/code"
TOKEN_URL = "https://github.com/login/oauth/access_token"
USER_URL = "https://api.github.com/user"
TIMEOUT = 15

_pending: dict | None = None
_lock = threading.Lock()


class SignInError(Exception):
    pass


def start() -> dict:
    """Ask GitHub for a code to show; returns what the student needs."""
    global _pending
    if not CLIENT_ID:
        raise SignInError("Sign in with GitHub isn't set up in this build — paste a fine-grained token instead")
    try:
        response = httpx.post(
            DEVICE_CODE_URL, data={"client_id": CLIENT_ID, "scope": SCOPE}, headers={"Accept": "application/json"}, timeout=TIMEOUT
        )
        response.raise_for_status()
        data = response.json()
    except httpx.HTTPError as e:
        raise SignInError(f"couldn't reach GitHub: {e}") from e
    if "device_code" not in data:
        raise SignInError(data.get("error_description") or data.get("error") or "GitHub didn't return a sign-in code")
    with _lock:
        _pending = {"device_code": data["device_code"], "expires_at": time.monotonic() + data["expires_in"]}
    return {
        "user_code": data["user_code"],
        "verification_uri": data["verification_uri"],
        "interval": data["interval"],
        "expires_in": data["expires_in"],
    }


def poll() -> dict:
    """One check with GitHub (the frontend waits `interval` seconds between
    calls): {"status": "pending" | "done" | "denied" | "expired" | "error"}."""
    global _pending
    with _lock:
        pending = _pending
    if pending is None or time.monotonic() > pending["expires_at"]:
        return {"status": "expired"}
    try:
        response = httpx.post(
            TOKEN_URL,
            data={
                "client_id": CLIENT_ID,
                "device_code": pending["device_code"],
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            },
            headers={"Accept": "application/json"},
            timeout=TIMEOUT,
        )
        data = response.json()
    except (httpx.HTTPError, ValueError) as e:
        return {"status": "error", "message": f"couldn't reach GitHub: {e}"}

    token = data.get("access_token")
    if token:
        keyring.set_password(config.CREDENTIAL_SERVICE, providers.COPILOT.credential, token)
        with _lock:
            _pending = None
        return {"status": "done", "login": _login(token)}

    error = data.get("error")
    if error == "authorization_pending":
        return {"status": "pending"}
    if error == "slow_down":
        return {"status": "pending", "interval": data.get("interval")}
    if error in ("access_denied", "expired_token"):
        with _lock:
            _pending = None
        return {"status": "denied" if error == "access_denied" else "expired"}
    return {"status": "error", "message": data.get("error_description") or error or "unexpected answer from GitHub"}


def _login(token: str) -> str | None:
    """Who signed in, to show it; nothing breaks without it."""
    try:
        response = httpx.get(USER_URL, headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}, timeout=TIMEOUT)
        response.raise_for_status()
        return response.json().get("login")
    except (httpx.HTTPError, ValueError):
        return None
