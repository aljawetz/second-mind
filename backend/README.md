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

## Running the full end-to-end integration check

Everything above tests one step in isolation (cached fixtures, simulated Canvas listings). This
chains all of them together against live data — real Canvas file → extract → embed → index →
sync manifest → retrieve — for a real course, catching anything that only breaks at the seams
between steps rather than inside any one of them.

```bash
uv run python3 scripts/integration_smoke_test.py
```

Not a pytest test (needs live Canvas access and real time — OCR + embedding across several real
files). Everything it touches lives in a `tempfile.TemporaryDirectory()`, nothing persists.
Defaults to course 55710 (18654-SV); edit `COURSE_ID`/`FILE_LIMIT` at the top of the script to
point elsewhere. `EXCLUDE_FILE_IDS` is a deliberate denylist — a file this script pulled once
already turned out to be a real named individual's personal document, not course material; kept
as an explicit guard rather than trusting "grab the first N files" not to pick it up again.

## Running the generation smoke test

Same real-data pattern as above, plus a real LLM call — verifies citations, the not-covered case
(a deliberately off-topic query should return zero source nodes, not a hallucinated answer), and
Socratic mode.

```bash
uv run python3 scripts/generation_smoke_test.py
```

Makes real, **billed** OpenAI API calls (a handful of cheap `gpt-4o-mini` queries, but real money,
not simulated). Needs a real OpenAI key in Keychain.

## Running the real `/ask` endpoint locally

`POST /courses/{course_id}/ask` (`main.py`) queries whatever index already exists at
`~/.ssb/default/index.lancedb/course_<id>` — there's no real onboarding→indexing pipeline wired up
yet (`OnboardingIndexing.tsx` in the frontend is still a simulated progress UI), so nothing builds
that index for you. To test the endpoint for real, populate it yourself first:

```python
# python3, from this directory
import canvas, ingestion, indexing
from pathlib import Path

structure = canvas.get_course_structure(YOUR_COURSE_ID)
# ...extract nodes the same way scripts/generation_smoke_test.py does...
indexing.build_index(nodes, Path.home() / ".ssb" / "default" / "index.lancedb", f"course_{YOUR_COURSE_ID}")
```

Then `uv run python3 main.py` and `curl -N -X POST http://127.0.0.1:8756/courses/{id}/ask -d
'{"question": "...", "mode": "answer"}'` — the response streams newline-delimited JSON (one
`{citations, grounded}` line, then one `{delta}` line per token, then `{done: true}`), chunked over
a `ThreadingHTTPServer` so it doesn't block other requests while streaming (implementation-plan.md
Step 9). A course with no index yet doesn't error — it returns the same shape with
`grounded: false` and the real not-covered copy, same as a genuinely off-topic query.

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
