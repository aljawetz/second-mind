# Data Model

How SSB stores everything on disk, and specifically how a course's identity and weekly schedule
are represented — the piece §9.1 (design spec) depends on. See [overview.md](overview.md) for how
this fits into the running system.

## 1. On-disk layout

Everything lives under `~/.ssb/<student_id>/` (§5.1 of the design spec — one directory per
student, physical isolation, not a filter on a shared store). `<student_id>` is derived locally at
onboarding, never a Canvas-issued identifier that could be reused to correlate across systems.

```
~/.ssb/<student_id>/
├── config.json                  # non-sensitive settings only — see §3
├── index.lancedb/                # one LanceDB database for this student
│   ├── course_49797/             # one table per course (logical separation, not a security
│   └── course_18654/             #   boundary — the security boundary is the directory itself)
├── courses/
│   ├── 49797/
│   │   ├── meta.json              # course code, name, term, weekly schedule (§2)
│   │   ├── manifest.db            # sync manifest (§5.5) — SQLite, schema in §4
│   │   └── sessions/
│   │       ├── 2026-09-12-class-06/
│   │       │   ├── audio.m4a
│   │       │   ├── transcript.json
│   │       │   └── notes.md
│   │       └── 2026-09-10-class-05/
│   │           └── ...
│   └── 18654/
│       └── ...
└── logs/
    └── sync.log
```

**Credentials are deliberately absent from this tree.** The Canvas token and LLM API key live in
the macOS Keychain (overview.md §4), never in `config.json` or anywhere under `~/.ssb/`. A backup
or sync tool that copies this directory should never be able to exfiltrate either credential as a
side effect.

**Raw downloaded files are not persisted.** A PDF, PPTX, or DOCX fetched from Canvas during sync
is hashed, extracted, embedded, and then discarded — not kept in this tree anywhere. Canvas remains
the source of truth for course files (unlike recordings/notes, which SSB itself originates and
must keep), so there's nothing to lose by not caching them: a re-extraction (a pipeline
improvement, a corrupted index) just re-downloads from Canvas rather than reading a local copy.
This also keeps disk usage bounded — one real course file seen this sprint was 36MB, and a
semester's worth of slide decks across several courses would add up fast if kept indefinitely.

## 2. Representing a course and its schedule

A course is identified by its Canvas course ID (stable, from the student's own enrollment) plus
locally-owned metadata that Canvas doesn't provide — chiefly the weekly meeting schedule, since
§9.1 established there's no reliable API source for it.

`courses/<id>/meta.json`:
```json
{
  "course_id": "49797",
  "code": "49797",
  "name": "Advanced AI for Industry and Society",
  "term": "Fall 2026",
  "schedule": [
    { "day": "tuesday",  "start": "17:00", "end": "18:20", "session_type": "lecture", "source": "manual" },
    { "day": "thursday", "start": "17:00", "end": "18:20", "session_type": "lecture", "source": "manual" }
  ],
  "schedule_exceptions": [
    { "date": "2026-10-13", "action": "skip", "reason": "Fall Break" }
  ]
}
```

- **`schedule`** is the recurring weekly pattern set at onboarding (§5.4) or edited later in
  Settings. `source` distinguishes a student-confirmed entry from an unconfirmed syllabus-text
  guess (§9.1) — the UI must never render a `"source": "syllabus-guess"` row identically to a
  confirmed one.
- **`schedule_exceptions`** handles one-off deviations from the recurring pattern — a cancelled
  class, a moved session — without editing the recurring rule itself and accidentally shifting
  every future week. This is the concrete mechanism behind the edge case named when this feature
  was first discussed: a professor moving one week's class shouldn't require re-entering the whole
  schedule.
- **Multiple session types per course** (a lecture and a recitation with different times) are just
  multiple entries in `schedule` with different `session_type` values, matching against different
  session-page templates if needed later — not a separate data structure.

## 3. `config.json` (non-sensitive, student-level)

```json
{
  "selected_courses": ["49797", "18654"],
  "llm_provider": "openai",
  "onboarding_complete": true
}
```
`llm_provider` names *which* provider the Keychain-stored key belongs to (so the backend knows
which API shape to call) — never the key itself.

`selected_courses` is what `unselect`/`DELETE` ([overview.md](overview.md) §2) actually mutate.
Unselecting a course removes its ID from this array only — `courses/<id>/` stays on disk
untouched, so re-adding the course later just re-appends the ID and resumes from the existing
manifest. Deleting a course removes the ID *and* recursively deletes `courses/<id>/` itself,
including its sessions.

## 4. Sync manifest schema (§5.5)

One `manifest.db` per course, one row per Canvas item ever seen for that course:

```sql
CREATE TABLE manifest (
  canvas_item_id   TEXT NOT NULL,
  item_type        TEXT NOT NULL,   -- 'page' | 'assignment' | 'announcement' | 'file'
  canvas_updated_at TEXT NOT NULL,
  content_hash     TEXT NOT NULL,   -- hash of extracted text, not raw bytes — see rag-pipeline.md
  last_synced_at   TEXT NOT NULL,
  PRIMARY KEY (canvas_item_id, item_type)
);
```

Kept separate from the vector store itself (rather than as extra columns on the LanceDB table) so
the diff step (§5.5) never needs to touch the vector store at all for unchanged items — it's a
plain SQLite query against a small table, independent of however large the index has grown.

**No `chunk_ids` column** — an earlier version of this schema tracked each item's chunk IDs
manually for deletion. LlamaIndex has a built-in mechanism for this: setting each `Document`'s
`doc_id` to the same value as `canvas_item_id` at ingestion time means deleting all of an item's
chunks on update or removal is a single `index.delete_ref_doc(canvas_item_id)` call, not a
manually-tracked list. **Needs verification before relying on it in Sprint 5** — there's a real,
open LlamaIndex issue reporting `delete_ref_doc` not working correctly in some configurations, so
this should be confirmed against the actual LanceDB integration, not assumed from the docs alone.

## 5. Session directories

Each session gets its own directory named for the date and class number
(`2026-09-12-class-06/`), not a bare UUID — so a student who goes looking through
`~/.ssb/<id>/courses/49797/sessions/` in Finder can find last Tuesday's class without opening the
app. `transcript.json` carries timestamped segments (the citation anchor for Q&A, matching the
`"Lecture 6 · 14:22"` label shape used throughout the mockup and §7); `notes.md` is plain
Markdown, editable outside SSB if the student ever wants to.
