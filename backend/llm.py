"""LLM provider interface for chat — the one place chat.py talks to a model.

Second Mind shouldn't be locked to one vendor: the goal is for each student to
connect the provider they already use. Messages and tools use the OpenAI
chat format (role/content/tool_calls/tool_call_id, JSON-schema tools) as the
shared shape, since every major provider maps onto it; a provider for
another vendor translates to and from that shape inside its own class.

OpenAI and DeepSeek speak OpenAI's chat completions API themselves, so
OpenAIProvider serves both; GitHub Copilot's translation lives in
copilot_llm.CopilotProvider. current_provider() picks between them.
"""

import json
from dataclasses import dataclass, field
from typing import Iterator, Protocol

import providers


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class TurnEnd:
    """Last item a stream_chat() call yields: any tool calls the model made.

    usage: {"prompt_tokens", "completion_tokens"} when the provider reports
    it (OpenAIProvider does, via stream_options), else None — callers
    that cost a call (the ask-modes evaluation) skip it when None rather
    than assume zero."""

    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: dict | None = None


class LLMProvider(Protocol):
    def stream_chat(
        self, messages: list[dict], tools: list[dict] | None, require_tool: bool = False
    ) -> Iterator[str | TurnEnd]:
        """Yield the reply's text as it arrives, then exactly one TurnEnd.
        require_tool: the model must call one of `tools` instead of answering."""
        ...


def current_provider() -> LLMProvider:
    """The provider the student chose at onboarding (providers.current())."""
    provider = providers.current()
    if provider.kind == "copilot":
        import copilot_llm

        return copilot_llm.CopilotProvider(provider)
    return OpenAIProvider(provider)


class OpenAIProvider:
    """Any provider speaking OpenAI's chat completions API."""

    def __init__(self, provider: providers.Provider | None = None, temperature: float = 0.1, api_key: str | None = None):
        # provider: the student's choice (providers.current()) unless given.
        # api_key: for scripts run outside the app (the memory evaluation);
        # the app always reads the Keychain.
        self._provider = provider or providers.current()
        self._client = providers.openai_client(self._provider, api_key)
        self._model = self._provider.model
        self._temperature = temperature
        self._extra = {"extra_body": self._provider.extra_body} if self._provider.extra_body else {}

    def complete_json(self, messages: list[dict], temperature: float = 0) -> object:
        """One non-streaming call in JSON mode — memory extraction and
        consolidation (memory/extract.py's JsonLLM) at temperature 0, study
        artifacts (study.py) higher, so asking again gives new questions. The
        reply parsed, or None if it isn't JSON after all: callers treat
        anything unexpected as "nothing to do", never as an error."""
        response = self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            temperature=temperature,
            response_format={"type": "json_object"},
            **self._extra,
        )
        try:
            return json.loads(response.choices[0].message.content or "")
        except json.JSONDecodeError:
            return None

    def stream_chat(
        self, messages: list[dict], tools: list[dict] | None, require_tool: bool = False
    ) -> Iterator[str | TurnEnd]:
        kwargs = {
            "model": self._model,
            "messages": messages,
            "temperature": self._temperature,
            "stream": True,
            "stream_options": {"include_usage": True},
            **self._extra,
        }
        if tools:
            kwargs["tools"] = tools
            if require_tool:
                kwargs["tool_choice"] = "required"
        # Tool calls arrive in pieces across chunks, keyed by index: the id and
        # name come once, the JSON arguments as string fragments. The usage
        # chunk (prompt/completion token counts) arrives last, on its own,
        # with an empty choices list — captured before the empty-choices
        # continue below, not instead of it.
        partial: dict[int, dict] = {}
        usage = None
        for chunk in self._client.chat.completions.create(**kwargs):
            if chunk.usage:
                usage = {"prompt_tokens": chunk.usage.prompt_tokens, "completion_tokens": chunk.usage.completion_tokens}
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta.content:
                yield delta.content
            for tc in delta.tool_calls or []:
                slot = partial.setdefault(tc.index, {"id": "", "name": "", "arguments": ""})
                if tc.id:
                    slot["id"] = tc.id
                if tc.function and tc.function.name:
                    slot["name"] = tc.function.name
                if tc.function and tc.function.arguments:
                    slot["arguments"] += tc.function.arguments
        calls = []
        for slot in (partial[i] for i in sorted(partial)):
            try:
                arguments = json.loads(slot["arguments"] or "{}")
            except json.JSONDecodeError:
                arguments = {}
            calls.append(ToolCall(id=slot["id"], name=slot["name"], arguments=arguments))
        yield TurnEnd(tool_calls=calls, usage=usage)
