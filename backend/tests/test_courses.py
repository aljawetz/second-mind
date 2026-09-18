"""courses.py — implementation-plan.md Step 13. Real filesystem + real
LanceDB table operations against a temp dir, no fixtures needed."""

from pathlib import Path

from llama_index.core.schema import TextNode

import config
import courses
import indexing


def test_unselect_removes_only_the_given_course_id(tmp_path: Path):
    config.write_config(tmp_path, {"selected_courses": [111, 222, 333], "onboarding_complete": True})
    courses.unselect_course(tmp_path, 222)
    assert config.read_config(tmp_path)["selected_courses"] == [111, 333]


def test_unselect_does_not_touch_course_directory(tmp_path: Path):
    config.write_config(tmp_path, {"selected_courses": [111]})
    course_dir = tmp_path / "courses" / "111"
    course_dir.mkdir(parents=True)
    (course_dir / "meta.json").write_text("{}")

    courses.unselect_course(tmp_path, 111)

    assert course_dir.exists()
    assert (course_dir / "meta.json").exists()


def test_has_local_data_false_when_nothing_exists(tmp_path: Path):
    db_path = tmp_path / "index.lancedb"
    assert courses.has_local_data(tmp_path, 999, db_path) is False


def test_has_local_data_true_when_course_dir_exists(tmp_path: Path):
    db_path = tmp_path / "index.lancedb"
    (tmp_path / "courses" / "111").mkdir(parents=True)
    assert courses.has_local_data(tmp_path, 111, db_path) is True


def test_delete_course_removes_directory_and_table_and_unselects(tmp_path: Path):
    db_path = tmp_path / "index.lancedb"
    config.write_config(tmp_path, {"selected_courses": [111]})
    course_dir = tmp_path / "courses" / "111"
    course_dir.mkdir(parents=True)
    (course_dir / "manifest.db").write_text("")
    node = TextNode(text="hello", metadata={"source": "x", "item_type": "file", "page": 1, "slide": None, "timestamp": None})
    indexing.build_index([node], db_path, "course_111")

    courses.delete_course(tmp_path, 111, db_path)

    assert not course_dir.exists()
    assert not indexing.index_exists(db_path, "course_111")
    assert config.read_config(tmp_path)["selected_courses"] == []


def test_delete_course_on_already_unselected_course_still_works(tmp_path: Path):
    db_path = tmp_path / "index.lancedb"
    config.write_config(tmp_path, {"selected_courses": []})
    course_dir = tmp_path / "courses" / "111"
    course_dir.mkdir(parents=True)

    assert courses.has_local_data(tmp_path, 111, db_path) is True
    courses.delete_course(tmp_path, 111, db_path)
    assert not course_dir.exists()
