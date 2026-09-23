"""Course unselect/delete — implementation-plan.md Step 13, overview.md's
`/courses/{id}/unselect` and `DELETE /courses/{id}`.

Two structurally distinct actions, not one endpoint with a flag:
unselect only touches config.json (data-model.md §3); delete is the
actual destructive path, removing the LanceDB table, the sync manifest,
and the entire courses/{id}/ directory — including every session
recording and note, which design spec §9.3 says are unrecoverable once
gone.
"""

import shutil
from pathlib import Path

import config
import indexing


def unselect_course(sm_home: Path, course_id: int) -> None:
    cfg = config.read_config(sm_home)
    selected = [c for c in cfg.get("selected_courses", []) if c != course_id]
    config.write_config(sm_home, {**cfg, "selected_courses": selected})


def has_local_data(sm_home: Path, course_id: int, db_path: Path) -> bool:
    """DELETE must work on an already-unselected course too (unselect,
    then later decide to actually delete it) — checking selected_courses
    membership the way the other course-scoped endpoints do would wrongly
    404 that real, valid case. This checks for real data instead: is there
    actually a directory or an index table to delete?"""
    course_dir = sm_home / "courses" / str(course_id)
    return course_dir.exists() or indexing.index_exists(db_path, f"course_{course_id}")


def delete_course(sm_home: Path, course_id: int, db_path: Path) -> None:
    indexing.drop_table(db_path, f"course_{course_id}")
    course_dir = sm_home / "courses" / str(course_id)
    if course_dir.exists():
        shutil.rmtree(course_dir)
    unselect_course(sm_home, course_id)
