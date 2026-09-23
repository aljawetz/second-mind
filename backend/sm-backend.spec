# PyInstaller spec, not the bare --onefile flag — see docs/architecture/overview.md §3
# and implementation-plan.md Step 1 for why: hidden imports and native deps get missed
# by the default flag once this backend grows beyond stdlib. Trivial today, same
# pipeline reused when LlamaIndex/onnxruntime/faster-whisper are added.
#
# Output is a folder (see the onedir note at the bottom), copied as-is to
# app/src-tauri/binaries/sm-backend/.
#
# BUILD FROM `uv sync --group build`, NEVER a plain `uv sync`. PyInstaller
# bundles whatever's importable in the venv it runs from, not just what
# main.py needs — building from an environment that also has `convert`
# installed (optimum, for the ONNX conversion script) silently pulled torch
# into this exact binary, confirmed by checking, implementation-plan.md
# Step 4. `pyinstaller sm-backend.spec` must be run as
# `uv run --group build pyinstaller sm-backend.spec ...`.

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

# onedir, not onefile: a onefile build unpacked its ~900 MB payload into a
# fresh temp dir on every launch, and macOS then scanned every newly written
# dylib — measured 34.5s to first /ping on a repeat launch, vs 2.2s for this
# layout (both pay a one-time ~35s scan on a never-seen build). The output
# is dist/sm-backend/ (the executable plus _internal/), shipped as a Tauri
# bundle resource rather than an externalBin, which only takes one file.
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="sm-backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="sm-backend")
