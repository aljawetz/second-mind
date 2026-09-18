# PyInstaller spec, not the bare --onefile flag — see docs/architecture/overview.md §3
# and implementation-plan.md Step 1 for why: hidden imports and native deps get missed
# by the default flag once this backend grows beyond stdlib. Trivial today, same
# pipeline reused when LlamaIndex/onnxruntime/faster-whisper are added.
#
# Output name matches Tauri's <name>-<target-triple> sidecar convention directly,
# so no manual rename step is needed after building.
#
# BUILD FROM `uv sync --group build`, NEVER a plain `uv sync`. PyInstaller
# bundles whatever's importable in the venv it runs from, not just what
# main.py needs — building from an environment that also has `convert`
# installed (optimum, for the ONNX conversion script) silently pulled torch
# into this exact binary, confirmed by checking, implementation-plan.md
# Step 4. `pyinstaller ssb-backend.spec` must be run as
# `uv run --group build pyinstaller ssb-backend.spec ...`.

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    # embeddings.py resolves MODEL_DIR relative to __file__, which under a
    # frozen build points into the bundle's internal extraction path, not
    # backend/ on disk — the model has to actually be bundled as data, not
    # just present on the build machine. Confirmed missing by actually
    # running a frozen build that imports indexing.py, not assumed.
    datas=[
        ("models/bge-small-en-v1.5-onnx", "models/bge-small-en-v1.5-onnx"),
        ("models/faster-whisper-base", "models/faster-whisper-base"),
    ],
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
