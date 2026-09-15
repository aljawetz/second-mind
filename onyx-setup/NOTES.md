# Local Onyx install notes

## What was installed

| Field | Value |
| --- | --- |
| Method | `onyx-cli deploy install` (after `uv tool install onyx-cli`) |
| Mode | **Standard** (full RAG: OpenSearch, Redis/cache, MinIO, model servers, background workers) |
| Version | `v4.7.3` |
| Deploy dir | `onyx-data/` (workspace-local; gitignored) |
| Compose project | `onyx-kingstown` (avoids clashing with `~/.config/onyx`) |
| URL | http://localhost:3000 (also published on :80) |
| Signup | http://localhost:3000/auth/signup (first user becomes admin) |

## Commands

```bash
# status / start / stop / uninstall (always pass --dir for this workspace install)
onyx-cli deploy status --dir onyx-data
onyx-cli deploy install --dir onyx-data --project onyx-kingstown   # restart existing
onyx-cli deploy stop --dir onyx-data
onyx-cli deploy uninstall --dir onyx-data --force                  # destroys data
```

## Notes

- Interactive installer defaults to **Lite** (option 1). Choose **2) Standard** for RAG/connectors.
- `--no-prompt` also defaults to Lite — do not use it when you want Standard.
- There is a separate older Standard install at `~/.config/onyx` (stopped); this workspace uses `onyx-data/`.
- LLM API keys are configured in the Onyx admin UI after signup, not in this repo.
- Standard wants ~10GB+ Docker RAM (preferred 16GB+). This machine’s Docker Desktop has ~15.6GB.
