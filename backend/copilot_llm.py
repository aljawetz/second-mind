"""GitHub Copilot as a model provider, through the Copilot SDK
(github-copilot-sdk) — the student's own Copilot plan pays for it.

The SDK drives a Copilot agent runtime (a separate process the SDK downloads
on first use, ~100 MB, into ~/Library/Caches/github-copilot-sdk), not a chat
completions endpoint, so this translates llm.py's interface onto it:

- Every model call is its own session, deleted afterwards. The runtime only
  takes user messages, not a transcript with roles, so the conversation so
  far (history, tool calls, their results) is written out as one message.
- Client mode "empty" plus available_tools: the runtime's built-in tools
  (shell, file edits) are never offered, only ours, and any permission
  request is refused. Ours are declarations only — Copilot asks for a
  tool, the session stops there, and chat.py runs the tool itself, exactly
  as with OpenAI.
- No tool_choice and no temperature: require_tool becomes an instruction,
  and JSON mode becomes "reply with only JSON" plus a tolerant parse.

The SDK is async; the backend is threaded. One event loop, on its own
thread, holds the one runtime for the life of the backend, and each call's
events come back through a queue.
"""

import asyncio
import json
import queue
import re
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from copilot import CopilotClient
from copilot.rpc import PermissionDecisionReject
from copilot.session_events import (
    AssistantMessageData,
    AssistantMessageDeltaData,
    AssistantUsageData,
    ExternalToolRequestedData,
    SessionErrorData,
    SessionIdleData,
)
from copilot.tools import Tool
from llama_index.core.llms import (
    CompletionResponse,
    CompletionResponseGen,
    CustomLLM,
    LLMMetadata,
)
from llama_index.core.llms.callbacks import llm_completion_callback

import providers
from llm import ToolCall, TurnEnd

# One model call, including Copilot choosing a model; generous, since a
# session that never goes idle would otherwise hang the request forever.
TURN_TIMEOUT_SECONDS = 180

# For LlamaIndex callers that send no system prompt of their own. "replace"
# swaps out the runtime's coding-agent prompt, which is wrong for a study app.
DEFAULT_SYSTEM = "You are Second Mind, a study assistant."

REQUIRE_TOOL = "Before replying, you must call one of your tools."
JSON_ONLY = "Reply with only the JSON object: no code fences, nothing before or after it."
CONTINUE = "That is the conversation so far, oldest first. Continue it as ASSISTANT: call a tool, or write your next reply."


@dataclass
class Turn:
    """Last item _stream yields: what the model asked for, and its usage."""

    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: dict | None = None


def _error(message: str, status: int | None = None) -> providers.CopilotError:
    """The runtime reports failures as text (a JSON-RPC error, or a session
    error that sometimes carries a status code); read the status from it."""
    lowered = message.lower()
    if status in (401, 403) or re.search(r"\b40[13]\b", message) or "bad credentials" in lowered or "not licensed" in lowered:
        # 403: a real token whose account has no Copilot plan.
        return providers.CopilotError(401, message)
    if status == 402 or "quota" in lowered or "premium request" in lowered:
        return providers.CopilotError(402, message)
    if status == 429 or re.search(r"\b429\b", message) or "rate limit" in lowered:
        return providers.CopilotError(429, message)
    return providers.CopilotError(502, message)


def _refuse(request, invocation):
    return PermissionDecisionReject(feedback="Second Mind doesn't allow this.")


async def _turn(client, token: str, model: str, system: str, prompt: str, tools: list[dict], out: queue.Queue) -> Turn:
    """One model call as one session: text deltas go to `out` as they arrive;
    returns the tool calls and usage once the model stops."""
    names = [t["function"]["name"] for t in tools]
    done = asyncio.Event()
    turn = Turn()
    streamed: set[str] = set()
    failure: list[providers.CopilotError] = []

    def on_event(event):
        data = event.data
        if isinstance(data, AssistantMessageDeltaData):
            streamed.add(data.message_id)
            out.put(data.delta_content)
        elif isinstance(data, AssistantMessageData):
            if data.content and data.message_id not in streamed:
                out.put(data.content)
            for request in data.tool_requests or []:
                if request.name in names:
                    turn.tool_calls.append(ToolCall(id=request.tool_call_id, name=request.name, arguments=request.arguments or {}))
            if turn.tool_calls:
                done.set()
        elif isinstance(data, ExternalToolRequestedData):
            # Normally already seen on the message itself.
            if not any(c.id == data.tool_call_id for c in turn.tool_calls):
                turn.tool_calls.append(ToolCall(id=data.tool_call_id, name=data.tool_name, arguments=data.arguments or {}))
            done.set()
        elif isinstance(data, AssistantUsageData):
            usage = turn.usage or {"prompt_tokens": 0, "completion_tokens": 0}
            usage["prompt_tokens"] += data.input_tokens or 0
            usage["completion_tokens"] += data.output_tokens or 0
            turn.usage = usage
        elif isinstance(data, SessionErrorData):
            failure.append(_error(data.message, data.status_code))
            done.set()
        elif isinstance(data, SessionIdleData):
            done.set()

    try:
        session = await client.create_session(
            model=model,
            github_token=token,
            streaming=True,
            system_message={"mode": "replace", "content": system or DEFAULT_SYSTEM},
            tools=[
                Tool(name=t["function"]["name"], description=t["function"].get("description", ""), parameters=t["function"].get("parameters"))
                for t in tools
            ],
            available_tools=[f"custom:{name}" for name in names],
            infinite_sessions={"enabled": False},
            on_permission_request=_refuse,
        )
    except Exception as e:
        raise _error(str(e)) from e
    session.on(on_event)
    try:
        try:
            await session.send(prompt)
            await asyncio.wait_for(done.wait(), TURN_TIMEOUT_SECONDS)
        except TimeoutError as e:
            raise providers.CopilotError(503, "GitHub Copilot didn't answer in time") from e
        except providers.CopilotError:
            raise
        except Exception as e:
            raise _error(str(e)) from e
        if failure:
            raise failure[0]
        if turn.tool_calls:
            # The session waits on our declared tool forever otherwise.
            await session.abort()
        return turn
    finally:
        await session.disconnect()
        await client.delete_session(session.session_id)


_loop: asyncio.AbstractEventLoop | None = None
_loop_lock = threading.Lock()
_client: CopilotClient | None = None
_client_lock: asyncio.Lock | None = None


def _event_loop() -> asyncio.AbstractEventLoop:
    global _loop
    with _loop_lock:
        if _loop is None:
            _loop = asyncio.new_event_loop()
            threading.Thread(target=_loop.run_forever, name="copilot", daemon=True).start()
    return _loop


async def _started_client() -> CopilotClient:
    """The runtime, started on first use and kept for the backend's life
    (startup is seconds; the first ever also downloads it)."""
    global _client, _client_lock
    if _client_lock is None:
        _client_lock = asyncio.Lock()
    async with _client_lock:
        if _client is None:
            # Empty mode needs its own storage rather than ~/.copilot, and
            # use_logged_in_user=False keeps a developer's own gh/Copilot CLI
            # login out of it: only the student's stored token counts.
            client = CopilotClient(mode="empty", base_directory=str(providers.SM_HOME / "copilot"), use_logged_in_user=False)
            try:
                await client.start()
            except Exception as e:
                raise providers.CopilotError(503, f"couldn't start GitHub Copilot: {e}") from e
            _client = client
    return _client


async def _run(token, model, system, prompt, tools, out) -> Turn:
    return await _turn(await _started_client(), token, model, system, prompt, tools, out)


_DONE = object()


def _stream(token: str, model: str, system: str, prompt: str, tools: list[dict]) -> Iterator[str | Turn]:
    """Text as it arrives, then one Turn — from any thread."""
    out: queue.Queue = queue.Queue()
    future = asyncio.run_coroutine_threadsafe(_run(token, model, system, prompt, tools, out), _event_loop())
    future.add_done_callback(lambda _: out.put(_DONE))
    while (item := out.get()) is not _DONE:
        yield item
    yield future.result()


def _flatten(messages: list[dict]) -> tuple[str, str]:
    """(system prompt, one message holding everything else)."""
    system = "\n\n".join(m["content"] for m in messages if m["role"] == "system" and m.get("content"))
    rest = [m for m in messages if m["role"] != "system"]
    if len(rest) == 1 and rest[0]["role"] == "user":
        return system, rest[0]["content"]
    tool_names: dict[str, str] = {}
    parts = []
    for m in rest:
        if m["role"] == "user":
            parts.append(f"USER:\n{m['content']}")
        elif m["role"] == "assistant":
            if m.get("content"):
                parts.append(f"ASSISTANT:\n{m['content']}")
            for call in m.get("tool_calls") or []:
                tool_names[call["id"]] = call["function"]["name"]
                parts.append(f"ASSISTANT called {call['function']['name']} {call['function']['arguments']}")
        elif m["role"] == "tool":
            parts.append(f"RESULT OF {tool_names.get(m['tool_call_id'], 'tool')}:\n{m['content']}")
    parts.append(CONTINUE)
    return system, "\n\n".join(parts)


def _parse_json(text: str) -> object:
    text = text.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


class CopilotProvider:
    """llm.py's provider interface (chat, memory) on GitHub Copilot."""

    def __init__(self, provider: providers.Provider, token: str | None = None):
        self._token = token or providers.api_key(provider)
        self._model = provider.model

    def stream_chat(self, messages: list[dict], tools: list[dict] | None, require_tool: bool = False) -> Iterator[str | TurnEnd]:
        system, prompt = _flatten(messages)
        if require_tool:
            prompt += "\n\n" + REQUIRE_TOOL
        for item in _stream(self._token, self._model, system, prompt, tools or []):
            if isinstance(item, Turn):
                yield TurnEnd(tool_calls=item.tool_calls, usage=item.usage)
            else:
                yield item

    def complete_json(self, messages: list[dict]) -> object:
        system, prompt = _flatten(messages)
        text = "".join(i for i in _stream(self._token, self._model, system, f"{prompt}\n\n{JSON_ONLY}", []) if isinstance(i, str))
        return _parse_json(text)


class CopilotLLM(CustomLLM):
    """A LlamaIndex LLM on GitHub Copilot (assignment explainer, session notes)."""

    model: str
    token: str

    @property
    def metadata(self) -> LLMMetadata:
        return LLMMetadata(context_window=128_000, num_output=-1, is_chat_model=False, model_name=self.model)

    @llm_completion_callback()
    def complete(self, prompt: str, formatted: bool = False, **kwargs: Any) -> CompletionResponse:
        text = "".join(i for i in _stream(self.token, self.model, "", prompt, []) if isinstance(i, str))
        return CompletionResponse(text=text)

    @llm_completion_callback()
    def stream_complete(self, prompt: str, formatted: bool = False, **kwargs: Any) -> CompletionResponseGen:
        def gen() -> CompletionResponseGen:
            text = ""
            for item in _stream(self.token, self.model, "", prompt, []):
                if isinstance(item, str):
                    text += item
                    yield CompletionResponse(text=text, delta=item)

        return gen()
