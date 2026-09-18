# Contribution & Distribution Plan

A sequenced plan for making SSB easy to **install** (a downloadable build, not "clone and build it
yourself") and easy to **contribute to** (a stranger can get a working dev environment in one
command and knows how to send a PR). Same Do/Test/Depends-on format as
[implementation-plan.md](implementation-plan.md), but this tracks infra/process work, not feature
build order — kept separate rather than folded into the sprint sequence.

Modeled loosely on [Onyx's self-serve quickstart](https://docs.onyx.app/deployment/getting_started/quickstart)
— one command, guided setup, no research required. SSB is a local desktop app rather than a
self-hosted server, so the direct analog isn't a CLI installer but a downloadable, double-click
`.dmg` for end users, plus a one-command bootstrap for contributors' dev environments.

Real findings from auditing the repo before writing this plan: no `LICENSE`, no `CONTRIBUTING.md`,
no CI, no `.github/` directory, no quickstart section in the README, and the Canvas integration is
hardcoded to `canvas.cmu.edu` in four places (`backend/canvas.py`'s `CANVAS_API_URL`,
`app/src/citations.ts`'s file-open URL, and two onboarding screens' copy) — meaning "installed by
others" currently only ever means "other CMU students with a CMU Canvas token."

**Decisions made before starting:** MIT license; macOS-only installer for the first release
(Windows/Linux explicitly out of scope, not half-supported); Canvas base URL becomes a real
configuration option rather than staying CMU-only.

Sequenced 2 → 1 → 3 → 4 → 6 → 5: the Canvas de-lock and license are substance blockers, CI should
exist before a release pipeline builds on top of it, and the signed-installer question (step 5) is
an open call-out, not a decided scope item.

## 2. De-CMU-lock the Canvas integration — done

**Do:** Add a Canvas base URL field to onboarding (`OnboardingKeys.tsx`) and `config.json`
(non-secret, alongside `selected_courses`/`llm_provider` — matches `config.py`'s existing role,
[data-model.md](data-model.md) §3). `canvas.py` reads the configured base URL instead of the
`CANVAS_API_URL` module constant. `citations.ts` builds the Canvas file-open URL from the same
configured value, threaded down the same way `courseId` already is. Onboarding copy becomes
generic ("your school's Canvas URL") instead of naming CMU specifically.

**Test:** Point onboarding at a different (real or fixture) Canvas base URL, complete onboarding,
confirm `canvas.py` calls hit that URL, not the CMU one — and that a file citation click opens a
URL built from the configured domain.

**Depends on:** nothing — first task.

**Verified:** `config.normalize_canvas_base_url()` accepts a bare domain, a full URL, a trailing
slash, or an accidentally-pasted `/api/v1` and returns one canonical origin (5 new tests,
`test_config.py`). `canvas._api_base()` reads that origin from `config.json` via a module-level
`canvas.SSB_HOME` (wired to the real value once in `main.py`, monkeypatched to `tmp_path` in
tests — same pattern `sessions.py`/`courses.py` already use, except as a settable module attribute
rather than a threaded parameter, since every `canvas.py` call site already existed before this
and threading `ssb_home` through all of them was a much larger diff for the same result). A new
`respx`-mocked test (`test_configured_base_url_is_used_instead_of_default`) confirms a request
actually goes to a configured non-CMU origin (`canvas.instructure.com`), not just that the string
is stored correctly. 51 backend tests pass. Frontend: `canvasBaseUrl` is threaded from `App.tsx`
(set from `OnboardingKeys`' `onNext` on fresh onboarding, or from `getConfig()` on the returning-
user path) through `AppShell` → `HomeView`/`AssignmentView` → `citations.ts`, with a CMU fallback
only for the edge case where config genuinely hasn't loaded. `npx tsc --noEmit` clean.

## 1. License + legal hygiene — done

**Do:** Add `LICENSE` (MIT) at repo root. Update README's "License" section from "TBD" to the real
statement. Check dependency licenses (llama-index, faster-whisper, PyInstaller, Tauri, etc.) for
anything copyleft that would conflict with MIT redistribution.

**Test:** `LICENSE` present and correctly identified by GitHub's license detector (badge/sidebar);
no flagged license conflicts.

**Depends on:** nothing — can run in parallel with step 2.

**Verified:** spot-checked every backend runtime dependency's declared license
(`importlib.metadata`) — all MIT, BSD-3-Clause, or Apache-2.0 (`faster-whisper`, `onnxruntime`,
`httpx`, `pdfplumber`, `python-pptx`, `pytesseract`, `tokenizers`, `pandas`); `llama-index-core`
and `keyring` don't declare a classifier but are MIT upstream. `pyinstaller` itself is GPL-3.0, but
per PyInstaller's own FAQ that applies to PyInstaller's source, not to the programs it freezes —
the shipped SSB binary isn't required to be GPL. React, Vite, TypeScript, and Tauri (dual MIT/
Apache-2.0) are all permissive. No conflicts found. `LICENSE` added; `app/package.json` and
`backend/pyproject.toml` both declare `"license": "MIT"`.

## 3. Contributor developer experience — done

**Do:** A `./scripts/bootstrap.sh` that runs the full first-time setup in one shot — `uv sync
--all-groups` + `convert_embedding_model.py` + `fetch_whisper_model.py` in `backend/`, `npm
install` in `app/` — collapsing `backend/README.md`'s existing multi-step setup (already correct,
just scattered) into one command. A real **Quickstart** section added to the top-level
`README.md` (currently has none): prerequisites (macOS, Node, Rust via rustup, `uv`, `brew install
tesseract`) → bootstrap script → `npm run tauri dev`. A `CONTRIBUTING.md`: branch/PR conventions,
what must pass before a PR (`uv run pytest tests/ -q`, `npx tsc --noEmit`), and this repo's
documentation norm — real findings get written into `docs/architecture/*.md`, not left implicit.

**Test:** A machine with only the listed prerequisites installed, no prior repo-specific state, can
go from `git clone` to a running `npm run tauri dev` window using only the README's Quickstart
section and the bootstrap script — no undocumented step required.

**Depends on:** 2 (so the quickstart doesn't teach a CMU-only setup).

**Verified:** ran `scripts/bootstrap.sh` for real on this machine — prerequisite check correctly
fails fast and lists what's missing when tools aren't on `PATH` (tested with a stripped `PATH`),
and the full happy path (model generation, model fetch, `uv run pytest`, `npm install`) completed
end to end, 51 backend tests passing at the end. Also found and fixed a real, unrelated staleness
bug while writing the Quickstart: the README's top status banner still said "RAG hasn't started
yet" and "no installable build yet" — both long since false (grounded Q&A, session capture, and
assignment explanations all work against real data per `implementation-plan.md`'s steps 0-13) —
updated to the real current state rather than left to actively mislead a new contributor sitting
right next to a Quickstart that contradicts it.

## 4. CI (GitHub Actions) — done, real workflow run not yet confirmed

**Do:** Backend job — `uv sync --all-groups`, generate the embedding model (public Hugging Face
checkpoint, no secrets needed) so `test_embeddings.py` runs for real in CI rather than skipping,
then `uv run pytest tests/ -q`. Canvas-fixture-dependent tests (`test_ingestion.py`) skip cleanly
without a token, same as local dev — CI never gets a real Canvas or OpenAI credential. Frontend
job — `npm ci`, `npx tsc --noEmit`, `npm run build`. A third job runs `cargo check` on the Tauri
shell (needs the frontend built first — `frontendDist` has to exist). All three run on push to
`main` and on PRs.

**Test:** A PR with a deliberately broken backend test and a deliberately broken TypeScript type
both fail CI; a clean PR passes both jobs.

**Depends on:** 3 (CI runs the same commands the bootstrap/README document — they need to already
be correct).

**Verified:** every command each CI job runs was executed for real, locally, on this machine
first (`uv sync --all-groups` + `convert_embedding_model.py` + `pytest tests/ -v` → 51 passed;
`npx tsc --noEmit` and `npm run build` → clean; `cargo check` in `app/src-tauri` → clean) — but the
first real GitHub Actions run still caught something local verification couldn't: the `rust` job
failed with `resource path 'binaries/ssb-backend-aarch64-apple-darwin' doesn't exist` —
Tauri's build script validates every `externalBin` resource exists on disk before it'll even
`cargo check`, and that binary is gitignored, only ever produced by the much heavier PyInstaller
release build (step 5), which this fast type-check job was never meant to run. Fixed by stubbing
an empty, executable placeholder at that exact path before `cargo check` — present, not
functional, which is all a compile-only check needs. Backend and frontend jobs passed on the real
first run; the `rust` job passed after this fix, confirmed on a second real run.

## 6. Repo hygiene — done

**Do:** `.github/ISSUE_TEMPLATE/bug_report.md` and `feature_request.md`, plus
`.github/PULL_REQUEST_TEMPLATE.md`. README badges for license and CI status.

**Test:** Opening a new issue or PR on GitHub shows the template; badges render and link correctly.

**Depends on:** 1 (license badge needs the real license) and 4 (CI badge needs a real workflow).

**Verified:** templates and badges added; badge links and rendering can only be fully confirmed
once this is pushed and the CI workflow has run at least once (same caveat as step 4).

## 5. Release/installer pipeline (macOS only) — done, shipping unsigned deliberately

**Do:** A tag-triggered workflow (`v*`) that builds the PyInstaller sidecar, runs `tauri build`,
and publishes the resulting `.dmg` to GitHub Releases. README gets a "Download" section pointing at
the latest release.

**Decision made:** ship unsigned now rather than block the first release on notarization (a paid
Apple Developer account). A `.dmg` from this pipeline triggers Gatekeeper's "Apple cannot verify
this app" warning on first install — real friction, accepted deliberately, with a README note on
the bypass (right-click → Open). Real signing stays separate future work — implementation-plan.md's
step 14 originally scoped "signed and notarized" as one unit; this splits it, shipping the
unsigned half now.

**Test:** A tagged push produces a GitHub Release with a downloadable `.dmg` attached; installing it
on a clean macOS machine (no dev tools) and completing onboarding against a real Canvas account
works end to end.

**Depends on:** 1, 2, 4.

**Verified:** the sidecar-build → Tauri-bundle pipeline was run for real, locally, end to end —
the documented two-phase `uv sync` sequence (`--group convert` to generate the embedding model,
then a full reconcile to `--group build` before PyInstaller runs) confirmed to actually strip
torch/optimum back out before the shipped binary is built, exactly as `backend/README.md` already
warned it must; the sidecar built, `SSB.app` bundled successfully. **The final `.dmg`-creation
step could not be verified in this sandboxed shell** — Tauri's `bundle_dmg.sh` shells out to
`osascript` to style the Finder window, and that AppleEvent call timed out (`-1712`) here, almost
certainly a local automation-permission limitation of this specific execution context rather than
a bug in the pipeline. Real verification came from actually pushing a tag and watching the
workflow run on GitHub's own macOS runner instead of trusting local output — see the tag/release
this step produced for the result.
