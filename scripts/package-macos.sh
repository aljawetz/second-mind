#!/usr/bin/env bash
# Finishes the macOS bundle that `npm run tauri build` produced, and
# rebuilds the .dmg from it. Run after both builds:
#   backend:  backend/dist/sm-backend/   (see backend/README.md)
#   app:      app/src-tauri/target/release/bundle/macos/Second Mind.app
#
# 1. Copies the backend into Contents/Resources/sm-backend/. It's a
#    PyInstaller onedir folder (backend/sm-backend.spec says why), which
#    Tauri can't bundle itself: externalBin takes a single file, and its
#    resource copier fails on the folder's symlinks. `ditto` keeps them.
#
# 2. Ad-hoc re-signs the finished bundle. Real bug found in v0.1.0: Tauri's
#    bundler never re-signs the assembled .app after copying in
#    Contents/Resources, so the only signature is the Rust linker's ad-hoc
#    one from compile time, whose CodeDirectory claims resources are sealed
#    when no _CodeSignature dir exists. macOS reports that mismatch as
#    "Second Mind is damaged and can't be opened". Adding the backend changes
#    Contents/Resources too, so this has to run after step 1.
#
# 3. Rebuilds the .dmg from the corrected .app instead of trusting Tauri's.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP="$ROOT/app/src-tauri/target/release/bundle/macos/Second Mind.app"
DMG_DIR="$ROOT/app/src-tauri/target/release/bundle/dmg"
BACKEND="$ROOT/backend/dist/sm-backend"

[[ -x "$BACKEND/sm-backend" ]] || { echo "error: $BACKEND/sm-backend missing; build the backend first (backend/README.md)" >&2; exit 1; }
[[ -d "$APP" ]] || { echo "error: $APP missing; run 'npm run tauri build' in app/ first" >&2; exit 1; }

rm -rf "$APP/Contents/Resources/sm-backend"
ditto "$BACKEND" "$APP/Contents/Resources/sm-backend"

codesign --force --deep --sign - "$APP"
codesign --verify --deep --strict --verbose=4 "$APP"

mkdir -p "$DMG_DIR"
rm -f "$DMG_DIR"/*.dmg
hdiutil create -volname "Second Mind" -srcfolder "$APP" -ov -format UDZO "$DMG_DIR/SecondMind.dmg"
echo "packaged: $DMG_DIR/SecondMind.dmg"
