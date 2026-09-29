#!/usr/bin/env bash
# Creates the self-signed code-signing certificate that package-macos.sh and
# dev-sign-and-run.sh sign Second Mind with. Run once, on the machine that
# builds releases; macOS asks for your login password once, to trust it.
#
# Why: the app keeps students' keys in the Keychain, and "Always Allow"
# there is tied to the program's signature. An ad-hoc signature changes with
# every build, so students were asked again after every update (and
# developers after every rebuild). With one certificate signing every build,
# the approval survives: it's tied to this certificate instead.
#
# Keep the exported .p12 this prints somewhere safe. Signing a release with
# a different certificate means every student approves once more.
# Doesn't replace an Apple Developer ID: Gatekeeper still treats the app as
# from an unidentified developer.
set -euo pipefail

NAME="${SM_SIGN_IDENTITY:-Second Mind Local Signing}"
KEYCHAIN="$HOME/Library/Keychains/login.keychain-db"
BACKUP="$HOME/second-mind-signing.p12"

if security find-identity -v -p codesigning | grep -qF "\"$NAME\""; then
  echo "'$NAME' is already set up"
  exit 0
fi

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
PASSWORD="$(/usr/bin/openssl rand -hex 16)"

# /usr/bin/openssl is LibreSSL, whose .p12 `security import` reads as is.
/usr/bin/openssl req -x509 -newkey rsa:2048 -nodes -days 7300 \
  -keyout "$TMP/key.pem" -out "$TMP/cert.pem" -subj "/CN=$NAME" \
  -addext "basicConstraints=critical,CA:false" \
  -addext "keyUsage=critical,digitalSignature" \
  -addext "extendedKeyUsage=critical,codeSigning"
/usr/bin/openssl pkcs12 -export -name "$NAME" -inkey "$TMP/key.pem" -in "$TMP/cert.pem" \
  -out "$TMP/identity.p12" -passout "pass:$PASSWORD"

# -T: codesign may use the key without asking each time.
security import "$TMP/identity.p12" -k "$KEYCHAIN" -P "$PASSWORD" -T /usr/bin/codesign
# codesign refuses an untrusted self-signed identity ("no identity found").
security add-trusted-cert -r trustRoot -p codeSign -k "$KEYCHAIN" "$TMP/cert.pem"

cp "$TMP/identity.p12" "$BACKUP"
chmod 600 "$BACKUP"
security find-identity -v -p codesigning | grep -F "\"$NAME\""
echo "backup: $BACKUP (password: $PASSWORD) — store both somewhere safe, then delete the file"
