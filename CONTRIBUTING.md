# Contributing to Second Mind

Thanks for looking at this. Second Mind is an open-source, self-hosted alternative to proprietary Canvas
AI tutors — see the [README](README.md) for what it does and why.

## Getting set up

```bash
git clone https://github.com/aljawetz/second-mind.git
cd second-mind
./scripts/bootstrap.sh
```

Needs `uv`, Node, Rust (`rustup`), and Tesseract (`brew install tesseract`) already installed —
the script checks for these up front and tells you what's missing rather than failing partway
through. It installs everything, generates the two local models (embedding + transcription,
~270MB combined, not committed to git — see `backend/README.md` for why), and runs the backend
test suite to confirm the environment is actually sound.

Then:

```bash
cd app
PATH="$HOME/.cargo/bin:$PATH" npm run tauri dev
```

Windows: run `python scripts\bootstrap.py` instead, then `npm run tauri dev` from `app` (setup
notes in the README). Released builds are macOS only for now — see
[docs/architecture/contribution-and-distribution-plan.md](docs/architecture/contribution-and-distribution-plan.md)
for why, and what's planned.

## Before opening a PR

```bash
cd backend && uv run pytest tests/ -q      # backend
cd app && npx tsc --noEmit                 # frontend
```

Both need to pass. If you touched anything under `app/src-tauri/`, also confirm `npm run tauri
dev` still launches cleanly — there's no automated check for the Rust shell itself yet.

## How this repo documents itself

Every backend `docs/architecture/*.md` file is kept current with **real findings**, not just
what a feature is supposed to do — a bug that only showed up in the frozen PyInstaller binary, an
API restriction found by actually calling Canvas, a design decision that got reversed after
testing. If your change surfaces something like that, a short note in the relevant doc (see
`docs/architecture/implementation-plan.md` for the pattern: **Do** / **Test** / **Real finding**)
is more valuable than a comment buried in the diff — the next person reading the code won't see
your PR description, but they will read the doc.

## Scope note

Second Mind explains assignments; it doesn't draft them, and no such feature is planned. See the
README's "Responsible AI" section and
[design spec §7.1](docs/specs/2026-09-14-second-mind-design.md) before proposing anything that would blur
that line — it's a deliberate, principled boundary, not a placeholder.

## Reporting bugs / proposing features

Open a GitHub issue — templates will guide you through the relevant details.
