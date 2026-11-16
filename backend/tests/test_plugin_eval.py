"""Mode P of ask_modes_eval.py: each question goes through `claude -p` with
the plugin loaded (plan 2026-11-13-claude-code-plugin.md, M0). These tests
cover the parts that run without Claude: the command line and turning the
stream-json events plus the MCP server's query log into an eval row.
"""

import datetime
import importlib.util
import json
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "ask_modes_eval.py"
TOOL = "mcp__plugin_second-mind_courses__search_course_material"


@pytest.fixture(scope="module")
def eval_mod():
    spec = importlib.util.spec_from_file_location("ask_modes_eval", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["ask_modes_eval"] = module
    spec.loader.exec_module(module)
    return module


def _assistant(*blocks):
    return {"type": "assistant", "message": {"content": list(blocks)}}


def _tool_use(name, tool_input):
    return {"type": "tool_use", "name": name, "input": tool_input}


def _result(text, session_id="s-1", cost=0.12, turns=4):
    return {
        "type": "result",
        "subtype": "success",
        "result": text,
        "session_id": session_id,
        "total_cost_usd": cost,
        "num_turns": turns,
        "usage": {"input_tokens": 10, "cache_read_input_tokens": 900, "cache_creation_input_tokens": 90, "output_tokens": 50},
    }


def _log(query, sources, texts=None, seconds=0.5, course_id=55016):
    return {"course_id": course_id, "query": query, "sources": sources, "texts": texts or ["t"] * len(sources), "seconds": seconds}


def test_command_loads_only_the_plugin_and_allows_only_its_tools(eval_mod):
    cmd = eval_mod.plugin_command("When is the final?", 55016, "Requirements", today=datetime.date(2026, 10, 21))

    assert cmd[:3] == ["claude", "-p", "When is the final?"]
    assert cmd[cmd.index("--plugin-dir") + 1] == str(eval_mod.PLUGIN_DIR)
    # No user settings, plugins or MCP servers; only the Skill tool built in.
    assert cmd[cmd.index("--setting-sources") + 1] == ""
    assert cmd[cmd.index("--tools") + 1] == "Skill"
    assert cmd[cmd.index("--allowedTools") + 1] == "mcp__plugin_second-mind_courses__*"
    assert cmd[cmd.index("--output-format") + 1] == "stream-json"
    prompt = cmd[cmd.index("--append-system-prompt") + 1]
    assert "Wednesday, October 21, 2026" in prompt
    assert "Requirements (course_id 55016)" in prompt
    assert "--resume" not in cmd and "--model" not in cmd


def test_command_resumes_a_chat_and_pins_a_model(eval_mod):
    cmd = eval_mod.plugin_command("and the midterm?", 55016, "Requirements", session_id="s-1", model="sonnet")

    assert cmd[cmd.index("--resume") + 1] == "s-1"
    assert cmd[cmd.index("--model") + 1] == "sonnet"


def test_environment_turns_off_claude_ai_connectors_and_pins_the_date(eval_mod, tmp_path):
    env = eval_mod.plugin_env(tmp_path / "q.jsonl", today=datetime.date(2026, 10, 21), base={"PATH": "/bin"})

    assert env == {
        "PATH": "/bin",
        "ENABLE_CLAUDEAI_MCP_SERVERS": "false",
        "SM_QUERY_LOG": str(tmp_path / "q.jsonl"),
        "SM_TODAY": "2026-10-21",
        "SM_SERVER_SOURCE": str(eval_mod.PLUGIN_DIR / "server"),
        "SM_MODELS_DIR": str(eval_mod.PLUGIN_DIR.parent / "backend" / "models"),
    }


def test_parse_reads_searches_citations_and_timings(eval_mod):
    events = [
        {"type": "system", "subtype": "init", "model": "claude-opus-5-5"},
        _assistant(_tool_use("Skill", {"skill": "second-mind:ask"})),
        _assistant(_tool_use("mcp__plugin_second-mind_courses__list_courses", {})),
        _assistant(_tool_use(TOOL, {"course_id": 55016, "query": "When is the final exam?"})),
        _assistant(_tool_use(TOOL, {"course_id": 55016, "query": "final exam date"})),
        _result("It is on Dec 4 [Class Preparation]. Worth 20% [Syllabus][syllabus · p.2]. See [made up]."),
    ]
    log = [
        _log("When is the final exam?", ["Class Preparation", "Syllabus"], ["Final on 12/4", "Exam 20%"], 6.1),
        _log("final exam date", ["syllabus · p.2"], ["Final 20%"], 0.4),
    ]

    out = eval_mod.parse_plugin_run(events, log, 55016)

    assert out["answer"].startswith("It is on Dec 4")
    assert out["searches"] == ["When is the final exam?", "final exam date"]
    assert out["retrieved"] == [["Class Preparation", "Syllabus"], ["syllabus · p.2"]]
    assert out["retrieved_texts"] == [["Final on 12/4", "Exam 20%"], ["Final 20%"]]
    # Only labels a search actually returned count as cited sources, in answer order.
    assert out["sources"] == ["Class Preparation", "Syllabus", "syllabus · p.2"]
    assert out["search_seconds"] == [6.1, 0.4]
    assert out["wrong_course_searches"] == []
    assert out["wrong_course_search_count"] == 0
    assert out["used_skill"] is True
    assert out["session_id"] == "s-1"
    assert out["model"] == "claude-opus-5-5"
    assert out["cost"] == 0.12
    assert out["llm_calls"] == 4
    assert out["prompt_tokens"] == 1000
    assert out["completion_tokens"] == 50


def test_parse_an_answer_with_no_search(eval_mod):
    out = eval_mod.parse_plugin_run([_result("The final is in December.")], [], 55016)

    assert out["searches"] == []
    assert out["retrieved"] == []
    assert out["sources"] == []
    assert out["used_skill"] is False


def test_parse_scores_only_searches_of_the_expected_course(eval_mod):
    events = [_result("Dec 4 [Syllabus], or maybe [Other Syllabus].")]
    log = [
        _log("final exam", ["Syllabus"], ["Final on 12/4"], 0.3),
        _log("final exam", ["Other Syllabus"], ["Final on 11/30"], 0.7, course_id=99999),
    ]

    out = eval_mod.parse_plugin_run(events, log, 55016)

    assert out["searches"] == ["final exam"]
    assert out["retrieved"] == [["Syllabus"]]
    assert out["retrieved_texts"] == [["Final on 12/4"]]
    assert out["search_seconds"] == [0.3]
    # A label only the other course returned is not a cited source.
    assert out["sources"] == ["Syllabus"]
    assert out["wrong_course_searches"] == [{"course_id": 99999, "query": "final exam"}]
    assert out["wrong_course_search_count"] == 1
    assert "wrong_course_search_count" in eval_mod.GRADES_FIELDS
    assert "wrong_course_searches" not in eval_mod.GRADES_FIELDS


def test_parse_a_failed_run_raises_with_its_message(eval_mod):
    failed = {"type": "result", "subtype": "error_during_execution", "is_error": True, "result": "boom"}

    with pytest.raises(RuntimeError, match="boom"):
        eval_mod.parse_plugin_run([failed], [], 55016)


def test_search_metrics_split_the_first_search_from_the_rest(eval_mod):
    out = {"retrieved": [["Class Preparation"], ["syllabus · p.2"]], "retrieved_texts": [["Final on 12/4"], ["Final 20%"]]}

    metrics = eval_mod.search_metrics(out, gold_source="syllabus — Grading", gold_facts=["Final 20%"])

    assert metrics == {
        "searched": True,
        "first_search_recall_at_5": False,
        "first_search_fact": False,
        "any_search_fact": True,
    }


def test_first_search_recall_looks_only_at_the_top_5(eval_mod):
    labels = ["A", "B", "C", "D", "E", "syllabus · Grading", "G"]

    metrics = eval_mod.search_metrics({"retrieved": [labels], "retrieved_texts": [["t"] * 7]}, gold_source="syllabus — Grading", gold_facts=None)

    assert metrics["first_search_recall_at_5"] is False


def test_search_metrics_without_a_search_or_gold(eval_mod):
    assert eval_mod.search_metrics({"retrieved": []}, gold_source=None, gold_facts=None) == {
        "searched": False,
        "first_search_recall_at_5": None,
        "first_search_fact": None,
        "any_search_fact": None,
    }


def test_course_id_for_a_name(eval_mod):
    assert eval_mod.course_id_for(eval_mod.COURSE_NAMES[55016]) == 55016


class _Proc:
    def __init__(self, stdout, returncode=0):
        self.stdout = stdout
        self.stderr = ""
        self.returncode = returncode


@pytest.fixture
def fake_claude(eval_mod, tmp_path, monkeypatch):
    """Stands in for subprocess.run: records each command, writes one log line
    for the course under test, and prints stream-json ending in a result."""
    monkeypatch.setattr(eval_mod, "_plugin_workdir", tmp_path)
    calls = []

    def run(cmd, env, **_kwargs):
        calls.append({"cmd": cmd, "log": Path(env["SM_QUERY_LOG"])})
        with open(env["SM_QUERY_LOG"], "a") as f:
            f.write(json.dumps(_log("final exam", ["Syllabus"], ["Final on 12/4"])) + "\n")
        events = [_assistant(_tool_use(TOOL, {"course_id": 55016, "query": "final exam"})), _result("Dec 4 [Syllabus].")]
        return _Proc("\n".join(json.dumps(e) for e in events) + "\n")

    monkeypatch.setattr(eval_mod.subprocess, "run", run)
    return calls


def test_run_p_scores_the_query_log_and_deletes_it(eval_mod, fake_claude):
    out = eval_mod.run_p(None, "When is the final?", [], eval_mod.COURSE_NAMES[55016])

    assert out["searches"] == ["final exam"]
    assert out["sources"] == ["Syllabus"]
    assert isinstance(out["seconds"], float)
    assert "--resume" not in fake_claude[0]["cmd"]
    # The log holds course text, so it must not outlive the run.
    assert not fake_claude[0]["log"].exists()


def test_run_p_resumes_the_session_on_a_follow_up(eval_mod, fake_claude):
    history = [{"question": "When is the final?", "answer": "Dec 4.", "session_id": "s-1"}]

    eval_mod.run_p(None, "and the midterm?", history, eval_mod.COURSE_NAMES[55016])

    cmd = fake_claude[0]["cmd"]
    assert cmd[cmd.index("--resume") + 1] == "s-1"


def test_run_p_without_a_result_event_raises_with_the_exit_code(eval_mod, tmp_path, monkeypatch):
    monkeypatch.setattr(eval_mod, "_plugin_workdir", tmp_path)
    monkeypatch.setattr(eval_mod.subprocess, "run", lambda *_a, **_k: _Proc('{"type": "system", "subtype": "init"}\n', returncode=1))

    with pytest.raises(RuntimeError, match="exited 1"):
        eval_mod.run_p(None, "When is the final?", [], eval_mod.COURSE_NAMES[55016])
