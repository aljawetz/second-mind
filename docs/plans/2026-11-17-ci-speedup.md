# CI speedup

Date: 2026-11-17

## Problem

PR CI wall clock is 12 to 28 minutes. Very little of that is real work.

Measured on two runs:

| Run | Total | Where the time went |
|---|---|---|
| `kahoot-export` (44183798856) | 12.5 min | ~10 min queued for a `macos-latest` runner, 1m50s `cargo check`. Backend 2 min, frontend 10s. |
| `windows-compatability-fix3` (44178820970) | 28 min | Windows job 26 min (breakdown below). macOS `cargo check` again started late from runner queue. |

### Windows job breakdown (26 min, cold Rust cache)

| Step | Time | Why |
|---|---|---|
| Toolchain setup (python, uv, node, rust) | 1.5 min | rustup install ~20s |
| `choco install tesseract` | 28s | |
| `uv sync` + model prep | 1 min | models cache miss (first run) |
| Backend pytest | 1m15s | |
| PyInstaller sidecar | 2m15s | Analysis alone is 2 min |
| Sidecar smoke tests + second `npm ci` | 30s | `npm ci` already ran earlier in the job |
| `tauri build` (release) | **8m25s** | Rust cache miss ("No cache found"), `CARGO_BUILD_JOBS=2` on a 4 vCPU runner |
| makensis | **4 min** | default LZMA compression over the whole sidecar |
| `cargo test` credential test | **3m10s** | debug profile, recompiles all 303 crates a second time |
| Install + smoke packaged app | 48s | |
| Upload + post-job cache saves | 3 min | rust-cache save alone 1m50s |

## Plan

Small stacked PRs, each with timing proof (before/after run links) in the description.

### PR 1: Skip macOS `cargo check` on PRs that don't touch Rust

`ci.yml`, `rust` filter: drop `app/src/**`, `app/package-lock.json`, `app/vite.config.*`. Keep `app/src-tauri/**` and `ci.yml`.

- Frontend changes can't break `cargo check`. It only needs `app/dist` to exist.
- Pushes to `main` still run the job (the `if` already allows `push`).
- Proof: a frontend-only PR shows the Tauri job as skipped, total under ~2.5 min.

### PR 2: Rust job caching

Add `Swatinem/rust-cache@v2` (`workspaces: app/src-tauri -> target`) to the `rust` job.

Optional, decide after PR 1 lands: move `cargo check` to `ubuntu-latest` to drop the macOS queue for PRs that do touch Rust. Safe today since `src-tauri` has no `target_os` code, but needs `libwebkit2gtk-4.1-dev` and friends via apt (~1 min). Keep macOS on `main` pushes if we go this way.

### PR 3: Split the Windows workflow into fast checks vs. installer

Lands on the Windows branch (or right after it merges), since `windows.yml` only exists there.

1. **`windows-tests` job (every PR, path-filtered):** backend pytest, frontend tests, credential `cargo test`. Target ~5 min warm.
2. **`windows-installer` job (`push` to `main`, `workflow_dispatch`, release, or a `build-windows` PR label):** PyInstaller, `tauri build`, NSIS, install + smoke.
3. Gate both on the `changes` job so a docs-only PR skips Windows entirely.

### PR 4: Make the installer build itself faster

1. **`CARGO_BUILD_JOBS`:** raise to 4 in CI. The RAM concern in `package-windows.py` is about laptops; the runner has 16 GB. Keep the script's `setdefault("2")` for local builds.
2. **Rust cache that actually hits:** caches are branch-scoped, and a PR can only read its own branch's cache or `main`'s. Once the installer job runs on `main` pushes, PRs get a warm cache. Expect `tauri build` to drop from 8.5 min to ~2 to 3 min.
3. **Credential test in release profile:** `cargo test --release --locked --lib windows_tests::...` reuses the release deps from `tauri build` instead of rebuilding 303 crates in debug. Saves ~3 min. Check that the test doesn't depend on `debug_assertions` first.
4. **NSIS compression off in CI:** pass `--config '{"bundle":{"windows":{"nsis":{"compression":"none"}}}}'` to `tauri build` from CI only. Accepted values are `zlib`, `bzip2`, `lzma` (default), `none`. Release builds keep LZMA. Saves most of the 4 min.
5. **Drop the duplicate `npm ci`:** add a `--skip-npm-ci` flag to `package-windows.py` (or skip when `node_modules` exists). Small, but free.
6. **Skip rust-cache save on PRs:** `save-if: ${{ github.ref == 'refs/heads/main' }}`. Cuts ~2 min of post-job time, and PR caches were unreadable by other PRs anyway.

Expected result: Windows PR checks ~5 min; installer build on `main` ~10 to 12 min warm instead of 26.

## Open questions

1. Which Windows branch is current, `windows-compatability-fix3` or `fix4`? PR 3 and 4 should stack on that one.
2. Do we want the installer on every PR via label, or only on `main` and releases?
3. Is the PyInstaller Analysis step (2 min) worth caching via `backend/build`? Risky (stale TOC), so not in this plan unless it becomes the bottleneck.
