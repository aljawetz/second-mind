#!/usr/bin/env bash
# Cargo's runner on macOS (app/src-tauri/.cargo/config.toml), so `tauri dev`
# — which launches the app with `cargo run` — starts a build signed with
# the local certificate (make-signing-cert.sh) instead of the linker's
# ad-hoc signature. That signature changes on every rebuild, and with it
# the Keychain's "Always Allow", which is why every rebuild asked for the
# password again. Without the certificate it still runs the binary, and says
# how to set the certificate up.
set -euo pipefail

NAME="${SM_SIGN_IDENTITY:-Second Mind Local Signing}"
if security find-identity -v -p codesigning 2>/dev/null | grep -qF "\"$NAME\""; then
  codesign --force --sign "$NAME" --identifier com.secondmind.app.dev "$1" 2>/dev/null ||
    echo "dev-sign-and-run: couldn't sign $1; running it unsigned" >&2
else
  echo "dev-sign-and-run: no '$NAME' certificate, so macOS asks for your password again after every rebuild." >&2
  echo "dev-sign-and-run: run ./scripts/make-signing-cert.sh once to stop that." >&2
fi
exec "$@"
