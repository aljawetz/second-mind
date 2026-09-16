# PyInstaller spec, not the bare --onefile flag — see docs/architecture/overview.md §3
# and implementation-plan.md Step 1 for why: hidden imports and native deps get missed
# by the default flag once this backend grows beyond stdlib. Trivial today, same
# pipeline reused when LlamaIndex/onnxruntime/faster-whisper are added.
#
# Output name matches Tauri's <name>-<target-triple> sidecar convention directly,
# so no manual rename step is needed after building.

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="ssb-backend-aarch64-apple-darwin",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    onefile=True,
)
