"""LLM provider interface for chat — the one place chat.py talks to a model.

Second Mind shouldn't be locked to one vendor: the goal is for each student to
connect the provider they already use. Messages and tools use the OpenAI
chat format (role/content/tool_calls/tool_call_id, JSON-schema tools) as the
shared shape, since every major provider maps onto it; a provider for
another vendor translates to and from that shape inside its own class.

Only OpenAI exists today. generation.py, explain.py and sessions.py still
build their own llama_index OpenAI clients — moving them here is separate
work.
"""

import json
from dataclasses import dataclass, field
from typing import Iterator, Protocol

import openai

import generation


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class TurnEnd:
    """Last item a stream_chat() call yields: any tool calls the model made."""

    tool_calls: list[ToolCall] = field(default_factory=list)


class LLMProvider(Protocol):
    def stream_chat(
        self, messages: list[dict], tools: list[dict] | None, require_tool: bool = False
    ) -> Iterator[str | TurnEnd]:
        """Yield the reply's text as it arrives, then exactly one TurnEnd.
        require_tool: the model must call one of `tools` instead of answering."""
        ...


class OpenAIProvider:
    def __init__(self, model: str = generation.DEFAULT_MODEL, temperature: float = 0.1, api_key: str | None = None):
        # api_key: for scripts run outside the app (the memory evaluation);
        # the app always reads the Keychain.
        self._client = openai.OpenAI(api_key=api_key or generation._get_llm_key())
        self._model = model
        self._temperature = temperature

    def complete_json(self, messages: list[dict]) -> object:
        """One non-streaming call in JSON mode, at temperature 0 — memory
        extraction and consolidation (memory/extract.py's JsonLLM). The
        reply parsed, or None if it isn't JSON after all: callers treat
        anything unexpected as "nothing to do", never as an error."""
        response = self._client.chat.completions.create(
            model=self._model, messages=messages, temperature=0, response_format={"type": "json_object"}
        )
        try:
            return json.loads(response.choices[0].message.content or "")
        except json.JSONDecodeError:
            return None

    def stream_chat(
        self, messages: list[dict], tools: list[dict] | None, require_tool: bool = False
    ) -> Iterator[str | TurnEnd]:
        kwargs = {"model": self._model, "messages": messages, "temperature": self._temperature, "stream": True}
        if tools:
            kwargs["tools"] = tools
            if require_tool:
                kwargs["tool_choice"] = "required"
        # Tool calls arrive in pieces across chunks, keyed by index: the id and
        # name come once, the JSON arguments as string fragments.
        partial: dict[int, dict] = {}
        for chunk in self._client.chat.completions.create(**kwargs):
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
        yield TurnEnd(tool_calls=calls)
