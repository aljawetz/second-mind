"""chat.py — the /ask tool loop, run against a scripted fake model and a fake
search, so these tests make no network or index calls."""

import pytest
from llama_index.core.schema import NodeRelationship, NodeWithScore, RelatedNodeInfo, TextNode

import chat
from llm import ToolCall, TurnEnd


def _node(node_id: str, source: str, text: str = "content") -> NodeWithScore:
    node = TextNode(id_=node_id, text=text, metadata={"source": source, "item_type": "file", "page": 1})
    node.relationships[NodeRelationship.SOURCE] = RelatedNodeInfo(node_id=f"file:{node_id}")
    return NodeWithScore(node=node, score=0.8)


class FakeProvider:
    """Plays back one scripted reply per model call and records what it was sent."""

    def __init__(self, replies):
        self._replies = list(replies)
        self.calls = []

    def stream_chat(self, messages, tools, require_tool=False):
        self.calls.append({"messages": [dict(m) for m in messages], "tools": tools, "require_tool": require_tool})
        text_pieces, tool_calls = self._replies.pop(0)
        yield from text_pieces
        yield TurnEnd(tool_calls=tool_calls)


def _run(question, replies, results, history=None):
    queries = []

    def search(query):
        queries.append(query)
        return results.get(query, [])

    provider = FakeProvider(replies)
    events = list(chat.answer(question, history or [], "Test Course", search, provider))
    text = "".join(e["delta"] for e in events if "delta" in e)
    final = next(e for e in events if "citations" in e)
    return text, final, events, queries, provider


def test_students_question_is_always_searched_first():
    text, final, events, queries, provider = _run(
        "When is the final exam?",
        replies=[(["It's on Dec 2 [1]."], [])],
        results={"When is the final exam?": [_node("a", "CourseInfo.pdf")]},
    )
    assert queries == ["When is the final exam?"]
    first_messages = provider.calls[0]["messages"]
    assert first_messages[-2]["tool_calls"][0]["function"]["name"] == "search_course"
    assert "[1] CourseInfo.pdf · p.1" in first_messages[-1]["content"]
    assert text == "It's on Dec 2 [1]."
    assert final["citations"] == [{"source_type": "file", "label": "CourseInfo.pdf · p.1", "item_id": "file:a"}]
    assert final["grounded"] is True
    assert events[-1] == {"done": True}


def test_model_searches_again_and_citations_are_renumbered_by_first_use():
    text, final, _, queries, _ = _run(
        "Explain the second one.",
        replies=[
            ([], [ToolCall(id="c1", name="search_course", arguments={"query": "fake objects"})]),
            (["A fake is lighter [3], unlike a stub [1]."], []),
        ],
        results={
            "Explain the second one.": [_node("a", "Stubs.pdf"), _node("b", "Other.pdf")],
            "fake objects": [_node("c", "Fakes.pdf")],
        },
    )
    assert queries == ["Explain the second one.", "fake objects"]
    assert text == "A fake is lighter [1], unlike a stub [2]."
    assert [c["label"] for c in final["citations"]] == ["Fakes.pdf · p.1", "Stubs.pdf · p.1"]


def test_citation_numbers_with_no_matching_source_are_dropped():
    text, final, *_ = _run(
        "q",
        replies=[(["True [1], invented [7]."], [])],
        results={"q": [_node("a", "A.pdf")]},
    )
    assert text == "True [1], invented."
    assert len(final["citations"]) == 1


def test_citation_split_across_stream_chunks_is_still_renumbered():
    text, final, *_ = _run(
        "q",
        replies=[([], [ToolCall(id="c1", name="search_course", arguments={"query": "more"})]), (["See [", "2", "] and [1, 2]."], [])],
        results={"q": [_node("a", "A.pdf")], "more": [_node("b", "B.pdf")]},
    )
    assert text == "See [1] and [2][1]."
    assert [c["label"] for c in final["citations"]] == ["B.pdf · p.1", "A.pdf · p.1"]


def test_same_chunk_found_twice_keeps_one_number():
    text, final, *_ = _run(
        "q",
        replies=[([], [ToolCall(id="c1", name="search_course", arguments={"query": "again"})]), (["Only one [2]."], [])],
        results={"q": [_node("a", "A.pdf")], "again": [_node("a", "A.pdf"), _node("b", "B.pdf")]},
    )
    assert text == "Only one [1]."
    assert [c["label"] for c in final["citations"]] == ["B.pdf · p.1"]


def test_nothing_found_and_nothing_cited_is_not_grounded():
    text, final, _, _, provider = _run(
        "When is Assignment 5 due?",
        replies=[(["I couldn't find that in the course materials."], [])],
        results={},
    )
    assert chat.NO_RESULTS in provider.calls[0]["messages"][-1]["content"]
    assert final == {"citations": [], "grounded": False}


def test_last_round_offers_no_tools_so_the_loop_ends():
    search_forever = ([], [ToolCall(id="c", name="search_course", arguments={"query": "x"})])
    _, _, _, queries, provider = _run("q", replies=[search_forever] * chat.MAX_TOOL_ROUNDS + [(["done"], [])], results={})
    assert len(provider.calls) == chat.MAX_TOOL_ROUNDS + 1
    assert provider.calls[-1]["tools"] is None
    assert len(queries) == 1 + chat.MAX_TOOL_ROUNDS


def test_history_is_sent_without_old_citation_numbers():
    history = [{"question": "Which doubles exist?", "answer": "Stubs, fakes [1][2] and mocks [3]."}]
    *_, provider = _run("Explain the second one.", replies=[(["ok"], [])], results={}, history=history)
    messages = provider.calls[0]["messages"]
    assert messages[1] == {"role": "user", "content": "Which doubles exist?"}
    assert messages[2] == {"role": "assistant", "content": "Stubs, fakes and mocks."}
    assert messages[3] == {"role": "user", "content": "Explain the second one."}


def test_follow_up_must_search_in_its_own_words_first():
    history = [{"question": "When is the midterm?", "answer": "Oct 7."}]
    *_, queries, provider = _run(
        "And the final?",
        replies=[([], [ToolCall(id="c1", name="search_course", arguments={"query": "final exam date"})]), (["Dec 2."], [])],
        results={},
        history=history,
    )
    assert provider.calls[0]["require_tool"] is True
    assert provider.calls[1]["require_tool"] is False
    assert queries == ["And the final?", "final exam date"]


def test_first_question_in_a_chat_may_answer_straight_away():
    *_, provider = _run("When is the midterm?", replies=[(["Oct 7."], [])], results={})
    assert provider.calls[0]["require_tool"] is False


def test_history_keeps_only_recent_turns():
    history = [{"question": f"q{i}", "answer": "a"} for i in range(10)]
    *_, provider = _run("now", replies=[(["ok"], [])], results={}, history=history)
    user_turns = [m["content"] for m in provider.calls[0]["messages"] if m["role"] == "user"]
    assert user_turns == [f"q{i}" for i in range(10 - chat.HISTORY_TURNS, 10)] + ["now"]


def test_prompt_names_the_course_and_the_general_knowledge_label():
    *_, provider = _run("q", replies=[(["ok"], [])], results={})
    system = provider.calls[0]["messages"][0]["content"]
    assert "Test Course" in system
    assert chat.GENERAL_KNOWLEDGE_LABEL in system


@pytest.mark.parametrize(
    "raw",
    ["nope", [{"question": "q"}], [{"question": "q", "answer": 3}], [["q", "a"]]],
)
def test_parse_history_rejects_bad_shapes(raw):
    with pytest.raises(ValueError):
        chat.parse_history(raw)


def test_parse_history_accepts_missing_and_valid():
    assert chat.parse_history(None) == []
    assert chat.parse_history([{"question": "q", "answer": "a", "extra": 1}]) == [{"question": "q", "answer": "a"}]


def test_unclosed_bracket_in_prose_is_not_held_forever():
    renumberer = chat.CitationRenumberer(lambda n: True)
    out = renumberer.feed("a list [like this one that never closes and keeps going")
    assert out == "a list [like this one that never closes and keeps going"


def test_a_dropped_citation_split_across_chunks_leaves_no_stray_space():
    text, *_ = _run("q", replies=[(["True", " [", "7]. Next."], [])], results={"q": [_node("a", "A.pdf")]})
    assert text == "True. Next."
