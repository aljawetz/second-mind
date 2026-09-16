# Canvas Integration

How SSB actually talks to Canvas — the concrete endpoints, the access restrictions found by
testing against a real course, and how §5.5's sync mechanism (design spec) maps onto real API
calls. See [overview.md](overview.md) for where this sits in the system and
[data-model.md](data-model.md) for what gets stored from it.

**Via a direct Canvas REST API client, owned by the backend** (design spec §10) — bearer-token
auth with the student's own Canvas API token, `Link`-header pagination, scoped to exactly the
endpoints in §3 below. Every access restriction in §2 is a real, tested property of the Canvas API
itself under a student-scoped token, independent of which client calls it.

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
| `get_course_structure` itself can 403 for an entire course/section, not just the Files listing | Checked directly this sprint — one of two Canvas IDs for the same nominal course (18654-SV) 403'd on this call entirely, the other didn't | Degrade per-endpoint, not just per-item: a course whose module/file tree is blocked should still sync via its assignment and page listings, which are separate calls |

**Syllabus text quality varies a lot by course — it's not universally unstructured.** Checked
across three real courses: the pilot course (56350) links a PDF with no inline schedule text, but
two of the other three have clean, directly parseable text (*"Classes: Mondays and Wednesdays,
1:00 PM to 2:50 PM"*; *"Class Schedule: Monday and Wednesday 3:00PM - 4:50PM"*). §9.1's syllabus
best-effort pre-fill is worth taking seriously as a real assist, not a token gesture — it just
happens that our own primary pilot course is the worst case, not the typical one. Manual entry
stays the primary, confirmed path regardless (§9.1) — this changes how often the assist actually
helps, not whether confirmation is still required.

**Real course pages lean heavily on links to things outside Canvas entirely** — Google Docs, Miro
boards, YouTube videos, and, in one real case, a Panopto-hosted lecture recording linked from a
course page. Two implications: it validates [sprint-02.md](../sprints/sprint-02.md)'s FR16
(external reading scraper) as addressing a real, observed pattern rather than a hypothetical one;
and it surfaces something not previously considered — **some professors already record and host
their own lectures**, a distinct content source from the student's own capture (design spec §9).
Not scoped in for the MVP, but worth naming rather than discovering later: if a course already
provides recordings, ingesting those could matter as much as capturing new ones.

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
