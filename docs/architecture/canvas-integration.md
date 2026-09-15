# Canvas Integration

How SSB actually talks to Canvas — the concrete endpoints, the access restrictions found by
testing against a real course, and how §5.5's sync mechanism (design spec) maps onto real API
calls. See [overview.md](overview.md) for where this sits in the system and
[data-model.md](data-model.md) for what gets stored from it.

**Via the Canvas MCP server, not a hand-rolled REST client** (design spec §10). The local backend
embeds it as a library/subprocess and calls its tools directly — the same integration already
validated through Sprint 3 and this sprint's PDF-ingestion PoC, including every access restriction
in §2 below, which were found using exactly this tool. Reusing a working integration rather than
rewriting Canvas auth, pagination, and endpoint coverage from scratch.

## 1. Authentication

The student generates their own Canvas API personal access token (Canvas Settings → New Access
Token) and pastes it during onboarding (§5.4). SSB never has institutional or admin-level
credentials — every request is scoped to exactly what that student can already see, which is both
the privacy model (§6: "only material the student already has access to") and the source of every
access restriction in §2 below.

## 2. Known access restrictions (found by testing, not assumed)

| Restriction | Found where | Workaround |
| --- | --- | --- |
| `list_course_files` (the Files-tab listing endpoint) 403s under a student token | Sprint 3 PoC, course 56350 | Files are still reachable individually through module items (`get_course_structure` → items of type `File` → fetch by `content_id`) even when the bulk listing endpoint is blocked |
| Privileged assignment fields (`assignment_visibility`, `overrides`) 403 | Original Sprint 3 Onyx-era finding | Don't request them; they're instructor-only fields with no student-facing equivalent needed |
| Disabled Pages tabs 404 the whole course's page listing | Original Sprint 3 finding | Treat a 404 on one content type as "this course doesn't expose that type," not a fatal ingestion error — degrade to the content types that did resolve |
| No calendar/schedule endpoint is exposed at all | Checked directly this sprint, course 56350 | Not worked around — this is why §9.1 makes manual schedule entry the primary path, not a fallback |
| Syllabus tab is often just a link to a file, not inline structured text | Checked directly this sprint, course 56350 | Same tiered extraction as any other file ([rag-pipeline.md](rag-pipeline.md)) — no special-casing, and no guarantee it contains parseable meeting times even then |

The pattern across all of these: **a student-scoped token is not a lesser version of an admin
token, it's a different access shape entirely**, with its own gaps that don't necessarily show up
until tested against a real course. Any new content type SSB starts ingesting should be tested
against a real course before being assumed to work.

## 3. Content types ingested, and their source endpoint

| Content type | Source | Notes |
| --- | --- | --- |
| Pages | Page listing + content endpoint | Full HTML body; extraction is straightforward (no tiering needed — it's already text) |
| Assignments | Assignment listing + details endpoint | Prompt text + due date/points/weight for the assignment explainer (§7.1) |
| Announcements | Announcement listing | Same shape as pages |
| Files (incl. PDFs, PPTX, DOCX) | Module items → individual file fetch (§2's workaround) | Routed through the tiered extraction pipeline ([rag-pipeline.md](rag-pipeline.md)) |
| Modules/module items | Course structure endpoint | Used for navigation/organization metadata and as the file-discovery path, not embedded as its own content |
| Personal data (grades, deadlines, submissions) | Fetched live, per request | **Never stored, never synced** — §5.2 of the design spec. Not part of this document's sync discussion at all |

## 4. Sync, mapped to real calls (§5.5)

Each course sync:

1. Pull the current listing (ID + `updated_at`) for pages, assignments, announcements, and the
   module/file tree — a handful of calls, metadata only.
2. Diff against `manifest.db` for that course ([data-model.md](data-model.md) §4) — new / changed /
   deleted / unchanged, exactly as specified in §5.5.
3. For **new** and **changed** items only, fetch full content and run it through ingestion.
4. Handle a 403/404 on any individual item as "skip this one, log it, continue" — not as a reason
   to abort the whole sync. A course with a disabled Pages tab should still get its assignments and
   files synced.

## 5. Rate limiting and API courtesy

Canvas enforces per-token rate limits. A sync across two courses with normal content volume is a
small number of requests and won't come close to any limit — but the sync engine should still back
off and retry on a 403/429 rather than hammering the API in a tight loop, both because it's the
respectful default and because a single misbehaving student install shouldn't be able to look like
abuse traffic against a shared institutional Canvas instance.
