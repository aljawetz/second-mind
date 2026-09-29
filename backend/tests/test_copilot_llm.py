"""copilot_llm.py — GitHub Copilot as a provider, through the Copilot SDK.
No runtime, no network, no token: _turn runs against a fake client whose
sessions replay scripted events, and the provider tests replace _stream."""

import asyncio
import queue
from types import SimpleNamespace

import pytest
from copilot.session_events import (
    AssistantMessageData,
    AssistantMessageDeltaData,
    AssistantMessageToolRequest,
    AssistantUsageData,
    SessionErrorData,
    SessionIdleData,
)

import copilot_llm
import credentials
import llm
import providers

SEARCH_TOOL = {
    "type": "function",
    "function": {"name": "search_course", "description": "Search", "parameters": {"type": "object", "properties": {"query": {"type": "string"}}}},
}


# --- _turn: one Copilot session per model call ------------------------------


class FakeSession:
    def __init__(self, events, raise_on_send=None):
        self.session_id = "s1"
        self._events = events
        self._raise_on_send = raise_on_send
        self._handler = None
        self.sent = None
        self.aborted = False
        self.disconnected = False

    def on(self, handler):
        self._handler = handler
        return lambda: None

    async def send(self, prompt, **kwargs):
        if self._raise_on_send:
            raise self._raise_on_send
        self.sent = prompt
        for data in self._events:
            self._handler(SimpleNamespace(type=None, data=data))
        return "m1"

    async def abort(self):
        self.aborted = True

    async def disconnect(self):
        self.disconnected = True


class FakeClient:
    def __init__(self, session):
        self.session = session
        self.options = None
        self.deleted = []

    async def create_session(self, **options):
        self.options = options
        return self.session

    async def delete_session(self, session_id):
        self.deleted.append(session_id)


def _run_turn(events, tools=(), raise_on_send=None):
    client = FakeClient(FakeSession(events, raise_on_send))
    out = queue.Queue()
    turn = asyncio.run(copilot_llm._turn(client, "github_pat_x", "auto", "SYSTEM", "PROMPT", list(tools), out))
    deltas = []
    while not out.empty():
        deltas.append(out.get())
    return turn, deltas, client


def test_turn_streams_text_and_cleans_up_the_session():
    turn, deltas, client = _run_turn(
        [
            AssistantMessageDeltaData(delta_content="Hel", message_id="m"),
            AssistantMessageDeltaData(delta_content="lo", message_id="m"),
            AssistantMessageData(content="Hello", message_id="m"),
            AssistantUsageData(model="gpt", input_tokens=12, output_tokens=3),
            SessionIdleData(),
        ]
    )
    assert deltas == ["Hel", "lo"]
    assert turn.tool_calls == []
    assert turn.usage == {"prompt_tokens": 12, "completion_tokens": 3}
    assert client.session.sent == "PROMPT"
    assert client.session.disconnected
    # Every model call is its own session: none may pile up on disk.
    assert client.deleted == ["s1"]


def test_a_message_that_was_never_streamed_still_comes_through():
    _, deltas, _ = _run_turn([AssistantMessageData(content="Whole reply", message_id="m"), SessionIdleData()])
    assert deltas == ["Whole reply"]


def test_session_offers_only_our_tools_and_refuses_everything_else():
    _, _, client = _run_turn([SessionIdleData()], tools=[SEARCH_TOOL])
    options = client.options
    assert options["available_tools"] == ["custom:search_course"]
    assert [t.name for t in options["tools"]] == ["search_course"]
    # Declaration only: Copilot asks for the tool, chat.py runs it.
    assert options["tools"][0].handler is None
    assert options["system_message"] == {"mode": "replace", "content": "SYSTEM"}
    assert options["github_token"] == "github_pat_x"
    decision = options["on_permission_request"](SimpleNamespace(), {})
    assert type(decision).__name__ == "PermissionDecisionReject"


def test_no_tools_means_none_available():
    _, _, client = _run_turn([SessionIdleData()])
    assert client.options["available_tools"] == []
    assert client.options["tools"] == []


def test_a_tool_request_ends_the_turn_and_aborts_the_session():
    turn, _, client = _run_turn(
        [
            AssistantMessageData(
                content="",
                message_id="m",
                tool_requests=[AssistantMessageToolRequest(name="search_course", tool_call_id="call_1", arguments={"query": "tcp"})],
            ),
        ],
        tools=[SEARCH_TOOL],
    )
    assert [(c.id, c.name, c.arguments) for c in turn.tool_calls] == [("call_1", "search_course", {"query": "tcp"})]
    assert client.session.aborted
    assert client.deleted == ["s1"]


def test_session_error_becomes_a_copilot_error_with_its_status():
    with pytest.raises(providers.CopilotError) as info:
        _run_turn([SessionErrorData(error_type="quota", message="You have no premium requests left", status_code=402)])
    assert info.value.status == 402


def test_bad_token_on_send_is_an_auth_error():
    # What the runtime really answers for a bad token (seen against it live).
    error = Exception("JSON-RPC Error -32603: Failed to fetch Copilot user info: 401 Unauthorized: Bad credentials")
    with pytest.raises(providers.CopilotError) as info:
        _run_turn([], raise_on_send=error)
    assert info.value.status == 401


@pytest.mark.parametrize(
    "message, status",
    [
        ("401 Unauthorized: Bad credentials", 401),
        ("403 Forbidden: not licensed to use Copilot", 401),
        ("quota exceeded for premium requests", 402),
        ("429 Too Many Requests", 429),
        ("something else broke", 502),
    ],
)
def test_error_status_is_read_from_the_message(message, status):
    assert copilot_llm._error(message).status == status


# --- CopilotProvider: the same interface chat.py and memory use --------------


def _fake_stream(items, seen):
    def stream(token, model, system, prompt, tools):
        seen.append({"token": token, "model": model, "system": system, "prompt": prompt, "tools": tools})
        yield from items

    return stream


def test_chat_history_and_tool_results_become_one_prompt(monkeypatch):
    seen = []
    monkeypatch.setattr(copilot_llm, "_stream", _fake_stream([copilot_llm.Turn()], seen))
    messages = [
        {"role": "system", "content": "Be a study assistant."},
        {"role": "user", "content": "What is TCP?"},
        {"role": "assistant", "content": None, "tool_calls": [{"id": "search-0", "type": "function", "function": {"name": "search_course", "arguments": '{"query": "TCP"}'}}]},
        {"role": "tool", "tool_call_id": "search-0", "content": "[1] TCP is a transport protocol."},
    ]

    list(copilot_llm.CopilotProvider(providers.COPILOT, token="t").stream_chat(messages, [SEARCH_TOOL]))

    call = seen[0]
    assert call["system"] == "Be a study assistant."
    assert "USER:\nWhat is TCP?" in call["prompt"]
    assert 'search_course {"query": "TCP"}' in call["prompt"]
    assert "RESULT OF search_course:\n[1] TCP is a transport protocol." in call["prompt"]
    assert call["tools"] == [SEARCH_TOOL]


def test_stream_chat_yields_text_then_turn_end(monkeypatch):
    calls = [llm.ToolCall(id="c", name="search_course", arguments={"query": "x"})]
    turn = copilot_llm.Turn(tool_calls=calls, usage={"prompt_tokens": 1, "completion_tokens": 2})
    monkeypatch.setattr(copilot_llm, "_stream", _fake_stream(["a", "b", turn], []))

    events = list(copilot_llm.CopilotProvider(providers.COPILOT, token="t").stream_chat([{"role": "user", "content": "hi"}], [SEARCH_TOOL]))

    assert events[:2] == ["a", "b"]
    assert isinstance(events[2], llm.TurnEnd)
    assert events[2].tool_calls == calls
    assert events[2].usage == {"prompt_tokens": 1, "completion_tokens": 2}


def test_require_tool_is_asked_for_in_the_prompt(monkeypatch):
    # Copilot has no tool_choice, so the instruction is all there is.
    seen = []
    monkeypatch.setattr(copilot_llm, "_stream", _fake_stream([copilot_llm.Turn()], seen))
    list(copilot_llm.CopilotProvider(providers.COPILOT, token="t").stream_chat([{"role": "user", "content": "hi"}], [SEARCH_TOOL], require_tool=True))
    assert "must call" in seen[0]["prompt"]


def test_a_single_message_is_sent_as_is(monkeypatch):
    seen = []
    monkeypatch.setattr(copilot_llm, "_stream", _fake_stream(['{"memories": []}', copilot_llm.Turn()], seen))
    reply = copilot_llm.CopilotProvider(providers.COPILOT, token="t").complete_json(
        [{"role": "system", "content": "Extract memories as JSON."}, {"role": "user", "content": "the chat"}]
    )
    assert reply == {"memories": []}
    assert seen[0]["prompt"].startswith("the chat")
    assert seen[0]["tools"] == []


@pytest.mark.parametrize(
    "text, parsed",
    [('```json\n{"a": 1}\n```', {"a": 1}), ('{"a": 1}', {"a": 1}), ("Sure! Here you go", None)],
)
def test_complete_json_tolerates_code_fences(monkeypatch, text, parsed):
    monkeypatch.setattr(copilot_llm, "_stream", _fake_stream([text, copilot_llm.Turn()], []))
    assert copilot_llm.CopilotProvider(providers.COPILOT, token="t").complete_json([{"role": "user", "content": "x"}]) == parsed


def test_llama_llm_completes_through_copilot(monkeypatch):
    monkeypatch.setattr(copilot_llm, "_stream", _fake_stream(["Step ", "one", copilot_llm.Turn()], []))
    llm_ = copilot_llm.CopilotLLM(model="auto", token="t")
    assert str(llm_.complete("Break this assignment down")) == "Step one"
    assert [r.delta for r in llm_.stream_complete("x")] == ["Step ", "one"]


# --- choosing Copilot ---------------------------------------------------------


def test_current_provider_is_copilot_when_chosen(tmp_path, monkeypatch):
    monkeypatch.setattr(providers, "SM_HOME", tmp_path)
    monkeypatch.setattr(credentials, "get", lambda key: "github_pat_x")
    providers.config.write_config(tmp_path, {"llm_provider": "copilot"})
    assert isinstance(llm.current_provider(), copilot_llm.CopilotProvider)
    assert isinstance(providers.llama_llm(), copilot_llm.CopilotLLM)


def test_current_provider_is_openai_compatible_otherwise(tmp_path, monkeypatch):
    monkeypatch.setattr(providers, "SM_HOME", tmp_path)
    monkeypatch.setattr(credentials, "get", lambda key: "sk-x" * 10)
    providers.config.write_config(tmp_path, {"llm_provider": "deepseek"})
    assert isinstance(llm.current_provider(), llm.OpenAIProvider)
