# Second Mind backend

The local sidecar Tauri spawns on app start (`app/src-tauri/src/lib.rs`). Binds to
`127.0.0.1:8756` only — see [docs/architecture/overview.md](../docs/architecture/overview.md) for
the API contract and [implementation-plan.md](../docs/architecture/implementation-plan.md) for
what's actually built and verified so far.

## Setup

```bash
uv sync --all-groups
```

Installs everything: runtime deps, tests, build tooling, and the one-time model-conversion tools.
Fine for day-to-day dev. The app's backend build never uses this venv; it has its own (see
"Building the backend for the app" below), so syncing here can't leak anything into the binary.

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

## Fetching the session-transcription model (one-time)

Not committed — `model.bin` alone is ~145MB. Needs network access to Hugging Face.

```bash
uv run python3 scripts/fetch_whisper_model.py
```

Produces `models/faster-whisper-base/` (gitignored). Bundled into the shipped binary the same way
as the embedding model above — implementation-plan.md Step 12 — rather than downloaded at runtime,
so session recording works fully offline once installed.

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

## Running the course sync smoke test

Real Canvas course, real files, real embedding — verifies a first sync produces new items and an
immediate re-sync (no remote changes) is a true no-op. Supersedes the old
integration_smoke_test.py, which only ever proved the "new -> unchanged" half of this.

```bash
uv run python3 scripts/course_sync_smoke_test.py
```

No OpenAI key needed — sync never calls an LLM, only the local embedding model. Needs
`models/bge-small-en-v1.5-onnx/` (`scripts/convert_embedding_model.py`).

## Running the generation smoke test

Same real-data pattern as above, plus a real LLM call — verifies citations and the not-covered
case (a deliberately off-topic query should return zero source nodes, not a hallucinated answer).

```bash
uv run python3 scripts/generation_smoke_test.py
```

Makes real, **billed** OpenAI API calls (a handful of cheap `gpt-4o-mini` queries, but real money,
not simulated). Needs a real OpenAI key in Keychain.

## Running the assignment explainer boundary test

```bash
uv run python3 scripts/assignment_explain_test.py
```

Real, billed. Re-runs design spec §7.1's manual boundary test as a scripted assertion against
course 55710's real "A1 - Test Doubles" assignment (a real coding assignment with concrete
class/method names) — asserts `explain.build_pointers()` never names any of them, only
`explain.build_breakdown()` may.

## Running the real `/ask` endpoint locally

`POST /courses/{course_id}/ask` (`main.py`) queries whatever index already exists at
`~/.secondmind/index.lancedb/course_<id>` — there's no real onboarding→indexing pipeline wired up
yet (`OnboardingIndexing.tsx` in the frontend is still a simulated progress UI), so nothing builds
that index for you. To test the endpoint for real, populate it yourself first:

```python
# python3, from this directory
import canvas, ingestion, indexing
from pathlib import Path

structure = canvas.get_course_structure(YOUR_COURSE_ID)
# ...extract nodes the same way scripts/generation_smoke_test.py does...
indexing.build_index(nodes, Path.home() / ".secondmind" / "index.lancedb", f"course_{YOUR_COURSE_ID}")
```

Then `uv run python3 main.py` and `curl -N -X POST http://127.0.0.1:8756/courses/{id}/ask -d
'{"question": "...", "mode": "answer"}'` — the response streams newline-delimited JSON (one
`{citations, grounded}` line, then one `{delta}` line per token, then `{done: true}`), chunked over
a `ThreadingHTTPServer` so it doesn't block other requests while streaming (implementation-plan.md
Step 9). A course with no index yet doesn't error — it returns the same shape with
`grounded: false` and the real not-covered copy, same as a genuinely off-topic query.

## Building the backend for the app

```bash
./scripts/build_sidecar.sh
```

Builds with PyInstaller and installs the result at `app/src-tauri/binaries/sm-backend/`, where
`npm run tauri dev` runs it from. Rerun it after changing backend code you want to see in the app.

It builds from its own venv, `backend/.venv-build`, holding only the main deps plus the `build`
group, so your everyday `.venv` stays free for tests and conversion tools. That split matters:
PyInstaller bundles whatever's importable in the venv it runs from, not just what `main.py`
reaches, and an environment that also had `convert` installed (`optimum`) once shipped real
`torch` submodules in the binary. The script fails the build if any torch module was bundled.

The output is a folder, not a single file (PyInstaller "onedir"): the single-file build unpacked
~900 MB to a fresh temp dir on every launch, and macOS rescanned it each time, so the backend took
~35s to answer on every launch instead of ~2s. Tauri can't bundle that folder itself (see
`scripts/package-macos.sh` at the repo root), so a release is packaged in two steps:

```bash
cd ../app && npm run tauri build -- --bundles app
cd .. && ./scripts/package-macos.sh   # adds the backend, re-signs, builds the .dmg
```
