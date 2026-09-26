"""chat.answer with agent memory — design spec §5.5, §5.7, §6. A real
MemoryService (scripted extraction model, word-hashing embedder) behind a
scripted chat model and a fake course search: no network, no model files.
test_chat.py covers chat without memory, which must not change."""

import json
import re
import zlib
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from llama_index.core.schema import NodeRelationship, NodeWithScore, RelatedNodeInfo, TextNode

import chat
from llm import ToolCall, TurnEnd
from memory import MemoryService

COURSE = 55710
SAID = datetime(2026, 9, 21, 18, 0, tzinfo=timezone.utc)
NOW = datetime(2026, 9, 28, 10, 0, tzinfo=timezone.utc)


def embed(text):
    v = [0.0] * 64
    for word in re.findall(r"\w+", text.lower()):
        v[zlib.crc32(word.encode()) % 64] += 1.0
    return v


class ScriptedLLM:
    def __init__(self):
        self.replies = []

    def complete_json(self, messages):
        return self.replies.pop(0)


def _extraction(text):
    memory = {"kind": "fact", "text": text, "importance": 4, "event_time": None, "entities": [], "task_ref_hint": None}
    return {"memories": [memory], "summary": "s"}


class FakeProvider:
    def __init__(self, replies):
        self._replies = list(replies)
        self.calls = []

    def stream_chat(self, messages, tools, require_tool=False):
        self.calls.append({"messages": [dict(m) for m in messages], "tools": tools})
        text_pieces, tool_calls = self._replies.pop(0)
        yield from text_pieces
        yield TurnEnd(tool_calls=tool_calls)


@pytest.fixture
def memory(tmp_path):
    """A course memory, and remember(text, *then) to tell it something,
    `then` being the consolidation replies that turn needs."""
    llm = ScriptedLLM()
    clock = {"t": SAID}
    with MemoryService(tmp_path, COURSE, llm=llm, embed=embed, now=lambda: clock["t"]) as svc:

        def remember(text, *then):
            clock["t"] = SAID
            llm.replies += [_extraction(text), *then]
            svc.observe([{"role": "user", "content": text}], conversation_id="c-old", turn_index=0)
            clock["t"] = NOW

        yield SimpleNamespace(service=svc, remember=remember)


def _node(node_id, source):
    node = TextNode(id_=node_id, text="content", metadata={"source": source, "item_type": "file", "page": 1})
    node.relationships[NodeRelationship.SOURCE] = RelatedNodeInfo(node_id=f"file:{node_id}")
    return NodeWithScore(node=node, score=0.8)


def _run(question, replies, memory, results=None):
    provider = FakeProvider(replies)
    search = lambda query: (results or {}).get(query, [])
    events = list(chat.answer(question, [], "Test Course", search, provider, memory=memory))
    text = "".join(e["delta"] for e in events if "delta" in e)
    final = next(e for e in events if "citations" in e)
    return text, final, provider


def _tool_result(provider, call_id, call=0):
    return next(m["content"] for m in provider.calls[call]["messages"] if m.get("tool_call_id") == call_id)


def _tool_names(tools):
    return [t["function"]["name"] for t in tools]


def test_without_memory_chat_offers_only_course_search():
    provider = FakeProvider([(["ok"], [])])
    events = list(chat.answer("q", [], "Test Course", lambda q: [], provider))

    assert _tool_names(provider.calls[0]["tools"]) == ["search_course"]
    assert "memories_used" not in next(e for e in events if "citations" in e)


def test_the_profile_and_the_memory_rules_go_into_the_system_prompt(memory):
    memory.remember("The student wants code examples in Java.")

    _, _, provider = _run("Show me a stub.", [(["ok"], [])], memory.service)

    system = provider.calls[0]["messages"][0]["content"]
    assert "Test Course" in system
    assert "recall_memory" in system and "forget_memory" in system
    assert "- The student wants code examples in Java. (since 2026-09-21)" in system
    assert _tool_names(provider.calls[0]["tools"]) == ["search_course", "recall_memory", "forget_memory"]


def test_an_empty_memory_adds_the_rules_but_no_profile(memory):
    _, final, provider = _run("Show me a stub.", [(["ok"], [])], memory.service)

    system = provider.calls[0]["messages"][0]["content"]
    assert "recall_memory" in system and "<memories>" not in system
    assert final["memories_used"] == []


def test_the_question_is_recalled_first_when_anything_matches(memory):
    memory.remember("The student is on team 4 with Priya.")

    _, final, provider = _run("Which team am I on?", [(["Team 4."], [])], memory.service)

    call = next(m for m in provider.calls[0]["messages"] if m["role"] == "assistant" and m["tool_calls"][0]["id"] == "recall-0")
    assert call["tool_calls"][0]["function"] == {
        "name": "recall_memory",
        "arguments": json.dumps({"query": "Which team am I on?"}),
    }
    assert _tool_result(provider, "recall-0") == "[M1] (fact, since 2026-09-21) The student is on team 4 with Priya."
    assert [m["text"] for m in final["memories_used"]] == ["The student is on team 4 with Priya."]


def test_nothing_recalled_adds_no_recall_result(memory):
    memory.remember("The student wants code examples in Java.")

    _, final, provider = _run("When is the midterm?", [(["Oct 7."], [])], memory.service)

    assert all(m.get("tool_call_id") != "recall-0" for m in provider.calls[0]["messages"])
    assert final["memories_used"] == []


def test_the_model_can_recall_what_changed_and_labels_carry_on(memory):
    memory.remember("The student's team does the recommender project.")
    memory.remember("The student's team does the fraud detection project.", {"decision": "UPDATE", "target": 1})

    _, final, provider = _run(
        "Which project do we do?",
        [
            ([], [ToolCall(id="r1", name="recall_memory", arguments={"query": "team project before", "include_history": True})]),
            (["Fraud detection, before that the recommender."], []),
        ],
        memory.service,
    )

    assert _tool_result(provider, "recall-0") == "[M1] (fact, since 2026-09-21) The student's team does the fraud detection project."
    # Labels carry on from the automatic recall's M1; the two memories match
    # this query equally well, so either may come first.
    history = _tool_result(provider, "r1", call=1)
    assert re.search(r"\[M[23]\] \(fact, since 2026-09-21\) The student's team does the fraud detection project\.", history)
    assert re.search(r"\[M[23]\] \(fact, 2026-09-21 to 2026-09-21, replaced\) The student's team does the recommender project\.", history)
    assert [m["text"] for m in final["memories_used"]] == [
        "The student's team does the fraud detection project.",
        "The student's team does the recommender project.",
    ]


def test_forget_deletes_a_memory_shown_this_turn(memory):
    memory.remember("The student is auditing the course.")

    _, final, provider = _run(
        "Forget that I'm auditing the course.",
        [([], [ToolCall(id="f1", name="forget_memory", arguments={"labels": ["M1"]})]), (["Done, forgotten."], [])],
        memory.service,
    )

    assert memory.service.list(include_inactive=True) == []
    result = _tool_result(provider, "f1", call=1)
    assert "The student is auditing the course." in result and "saved chat" in result
    assert final["memories_used"] == []  # the app must not show forgotten text


def test_forget_refuses_a_label_that_was_not_shown_this_turn(memory):
    memory.remember("The student is auditing the course.")

    _, _, provider = _run(
        "Forget that I'm auditing the course.",
        [([], [ToolCall(id="f1", name="forget_memory", arguments={"labels": ["M3", "whatever"]})]), (["Hmm."], [])],
        memory.service,
    )

    assert len(memory.service.list()) == 1
    assert "M3" in _tool_result(provider, "f1", call=1)


def test_memory_labels_never_reach_the_answer_but_course_citations_do(memory):
    memory.remember("The student is on team 4 with Priya.")

    text, final, _ = _run(
        "Who should I ask about the team project?",
        [(["You're on team 4 [M1], so ask Priya [1][M1, M2]."], [])],
        memory.service,
        results={"Who should I ask about the team project?": [_node("a", "Project.pdf")]},
    )

    assert text == "You're on team 4, so ask Priya [1]."
    assert [c["label"] for c in final["citations"]] == ["Project.pdf · p.1"]


def test_a_memory_label_split_across_chunks_leaves_no_stray_space(memory):
    text, _, _ = _run("q", [(["Use Java", " [M", "1]. Here", " it is."], [])], memory.service)

    assert text == "Use Java. Here it is."
