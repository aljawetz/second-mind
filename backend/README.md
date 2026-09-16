# SSB backend

The local sidecar Tauri spawns on app start (`app/src-tauri/src/lib.rs`). Binds to
`127.0.0.1:8756` only — see [docs/architecture/overview.md](../docs/architecture/overview.md) for
the API contract and [implementation-plan.md](../docs/architecture/implementation-plan.md) for
what's actually built and verified so far.

## Setup

```bash
uv sync --all-groups
```

Installs everything: runtime deps, tests, build tooling, and the one-time model-conversion tools.
Fine for day-to-day dev. **Don't use this to build the shipping binary** — see below.

### Dependency groups aren't additive across separate `uv sync` calls

Each `uv sync --group X` *reconciles* the environment to exactly "main deps + that group,"
discarding packages from any group not named in that call. `uv sync --group test` then
`uv sync --group convert` next will silently remove `pytest`/`respx` picking up `optimum`. Combine
groups in one call if you need more than one (`uv sync --group test --group convert`), or just use
`--all-groups` for normal dev work.

## Running tests

```bash
uv sync --all-groups   # or at minimum --group test
uv run pytest tests/ -v
```

The Canvas tests (`tests/test_canvas.py`) replay real captured fixtures — no live Canvas access
needed. The embedding tests (`tests/test_embeddings.py`) skip cleanly with a clear reason until
you've generated the model (next section).

## Generating the embedding model (one-time)

Not committed — `model.onnx` alone is ~128MB, over GitHub's 100MB push limit, and it's
deterministically regenerable from a public checkpoint. Needs network access to Hugging Face.

```bash
uv sync --all-groups   # or at minimum --group convert
uv run python3 scripts/convert_embedding_model.py
```

Produces `models/bge-small-en-v1.5-onnx/` (gitignored). See
[docs/architecture/rag-pipeline.md §3](../docs/architecture/rag-pipeline.md) for why this exists —
avoids bundling `torch` into the shipped app.

## Fetching ingestion test fixtures (one-time)

Not committed, and not regenerable from a public source — these are an instructor's actual course
materials, not ours to redistribute in a public repo. Needs a Canvas token in Keychain
(onboarding, or Step 2's flow) with access to course 56350.

```bash
uv run python3 scripts/fetch_ingestion_fixtures.py
```

Produces `tests/fixtures/ingestion/` (gitignored). The measured baseline derived from them —
character counts, page/slide counts, which pages need OCR fallback — *is* committed
(`tests/fixtures/ingestion_baseline.json`), since that's our own data, not the instructor's
content. `tests/test_ingestion.py` skips cleanly if you haven't run this yet. Also needs Tesseract
installed locally for the OCR tests (`brew install tesseract` on macOS) — not a Python package,
`pytesseract` only wraps the binary.

## Building the sidecar binary

```bash
uv sync --group build
uv run --group build pyinstaller ssb-backend.spec --distpath dist --workpath build
```

**Must be `--group build` alone, never `--all-groups` or a plain `uv sync`.** PyInstaller bundles
whatever's importable in the venv it's run from, not just what `main.py` actually reaches — an
environment that also has `convert` installed (`optimum`, needed only for the ONNX conversion
above) silently bundled real `torch` submodules into the shipped binary once, confirmed by
checking the build's own analysis output:

```bash
grep -c "^  ('torch\." build/ssb-backend/Analysis-00.toc   # must print 0
```

Copy the result into the Tauri bundle:

```bash
cp dist/ssb-backend-aarch64-apple-darwin ../app/src-tauri/binaries/
```
