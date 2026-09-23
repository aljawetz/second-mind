"""Re-extract every Canvas item (files, pages, assignments, syllabus) for the
selected courses, keeping class recordings and notes.

Sync only re-reads an item when Canvas reports it changed, so a change to
how content is extracted or chunked (ingestion.py, indexing.py) never
reaches items that are already indexed. This forgets every Canvas item in a
course's sync manifest, deletes its chunks, and runs a normal sync, which
then sees everything as new. Session transcripts and notes aren't Canvas
items, aren't in the manifest, and are left alone.

Not a migration: run it by hand after an extraction change. Quit the app
first so nothing else writes to the index. Needs the Canvas token in
Keychain, like the app. From backend/:

    uv run python3 scripts/reindex_canvas_content.py [course_id ...]
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import canvas
import config
import course_sync
import indexing
import sync

SM_HOME = Path.home() / ".secondmind"
canvas.SM_HOME = SM_HOME


def reindex(course_id: int) -> None:
    db_path = SM_HOME / "index.lancedb"
    table_name = f"course_{course_id}"
    manifest_path = SM_HOME / "courses" / str(course_id) / "manifest.db"
    if manifest_path.exists():
        conn = sync.open_manifest(manifest_path)
        items = conn.execute("SELECT canvas_item_id, item_type FROM manifest").fetchall()
        for item_id, item_type in items:
            indexing.delete_ref_doc_nodes(db_path, table_name, item_id)
            sync.forget(conn, item_id, item_type)
        conn.close()
        print(f"[{course_id}] forgot {len(items)} Canvas items")

    done = failed = 0
    for event in course_sync.sync_course(course_id, SM_HOME):
        if event.get("done"):
            print(f"[{course_id}] sync finished: {event}")
        elif event.get("status") == "failed":
            failed += 1
            print(f"[{course_id}] failed: {event.get('item')}: {event.get('error')}")
        else:
            done += 1
    print(f"[{course_id}] {done} items indexed, {failed} failed")


if __name__ == "__main__":
    ids = [int(a) for a in sys.argv[1:]] or config.read_config(SM_HOME).get("selected_courses", [])
    for course_id in ids:
        reindex(course_id)
    # Same as main._exit_now: normal interpreter teardown can abort in ONNX
    # Runtime's and Arrow's native destructors ("recursive_mutex lock
    # failed") after all the work is already saved.
    sys.stdout.flush()
    os._exit(0)
