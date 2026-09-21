"""Course sync smoke test — docs/superpowers/specs/2026-09-20-course-sync-phase1-design.md.
Real Canvas course, real files, real embedding — proves the new -> unchanged
round-trip end-to-end against live data (the same proof the old
integration_smoke_test.py provided, which this script supersedes and
replaces). Changed-item and removed-item branching logic is NOT re-proven
here against live data — mutating or deleting real Canvas content as part
of a test is out of scope for this project. That logic is already covered,
with real assertions (not just mocks recording calls), by
tests/test_course_sync.py's mocked unit tests.

Not a pytest test: needs live Canvas access and takes real time
(embedding + OCR on real files). Run directly:

    uv run python3 scripts/course_sync_smoke_test.py

Needs a real OpenAI-independent local setup: models/bge-small-en-v1.5-onnx/
(scripts/convert_embedding_model.py) — no LLM key needed, sync never calls
one.
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import course_sync

COURSE_ID = 55710  # 18654-SV, Software Testing and Operations


def log(msg: str):
    print(f"[sync-smoke] {msg}")


def run_once(course_id: int, ssb_home: Path) -> dict:
    summary = None
    for event in course_sync.sync_course(course_id, ssb_home):
        if event.get("done"):
            summary = event
        elif event.get("status") == "failed":
            log(f"  FAILED: {event['item']}: {event['error']}")
        else:
            log(f"  synced: {event['item']}")
    return summary


def main():
    with tempfile.TemporaryDirectory() as scratch:
        ssb_home = Path(scratch)

        log(f"first sync of course {COURSE_ID} (real Canvas call)")
        summary = run_once(COURSE_ID, ssb_home)
        log(f"  summary: {summary}")
        assert summary.get("error") is None, f"course sync failed outright: {summary}"
        assert summary["new"] > 0, "expected at least one new item on a first sync"

        log("re-syncing the same course with no remote changes — expect all zero")
        summary2 = run_once(COURSE_ID, ssb_home)
        log(f"  summary: {summary2}")
        assert summary2 == {"done": True, "new": 0, "changed": 0, "removed": 0, "failed": 0}, (
            f"expected a no-op re-sync, got {summary2}"
        )

        log("ALL CHECKS PASSED — a real course syncs, and a no-change re-sync is a true no-op")


if __name__ == "__main__":
    main()
