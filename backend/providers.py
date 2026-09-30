"""Which model provider answers — chosen by the student during onboarding and
saved as config.json's llm_provider.

OpenAI and DeepSeek speak OpenAI's chat completions API, so each is just a
base URL, a model, the Keychain item holding its key, and any extra request
fields it needs. GitHub Copilot doesn't — it goes through the Copilot SDK
(copilot_llm.py) — but is chosen, keyed and named the same way. llm.py
(chat, memory), generation.py, explain.py and sessions.py all build their
clients from here.

No LlamaIndex import at module level: main.py imports this at startup to
answer /credentials/status, and keeps the LlamaIndex stack out of that path.
"""

from dataclasses import dataclass, field
from pathlib import Path

import keyring
import openai

import config

SM_HOME = Path.home() / ".secondmind"  # set to the real value by main.py at startup; tests monkeypatch this directly


@dataclass(frozen=True)
class Provider:
    id: str
    name: str  # for error messages the student sees
    kind: str  # "openai" (chat completions API) or "copilot" (Copilot SDK)
    credential: str  # Keychain item, same service as the Canvas token
    model: str
    base_url: str | None = None  # None: the openai SDK's own default
    # Only needed for models llama_index can't look up itself (non-OpenAI).
    context_window: int | None = None
    # Provider-specific request fields, sent on every call.
    extra_body: dict = field(default_factory=dict)


OPENAI = Provider(id="openai", name="OpenAI", kind="openai", credential="openai-key", model="gpt-4o-mini")

# Thinking mode is DeepSeek's default. It ignores temperature, and on any
# request carrying tools it requires every earlier reply's reasoning_content
# passed back (a 400 otherwise) — chat.py's message history doesn't carry
# that, so thinking stays off.
DEEPSEEK = Provider(
    id="deepseek",
    name="DeepSeek",
    kind="openai",
    credential="deepseek-key",
    model="deepseek-flash",
    base_url="https://api.deepseek.com",
    context_window=1_000_000,
    extra_body={"thinking": {"type": "disabled"}},
)

# A fine-grained personal access token with the Copilot Requests permission
# (or an OAuth token); billed to the student's own Copilot plan. "auto" lets
# Copilot pick the model, so a retired model name can't break the app.
COPILOT = Provider(id="copilot", name="GitHub Copilot", kind="copilot", credential="github-copilot-token", model="auto")

PROVIDERS = {p.id: p for p in (OPENAI, DEEPSEEK, COPILOT)}


class CopilotError(Exception):
    """A failed Copilot call. The openai SDK's errors carry an HTTP status
    for main.py's _llm_error; this carries the same, read from the Copilot
    runtime's error (copilot_llm._error)."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def current() -> Provider:
    """The provider config.json names; OpenAI when it names none (everyone
    onboarded before there was a choice)."""
    provider_id = config.read_config(SM_HOME).get("llm_provider") or OPENAI.id
    if provider_id not in PROVIDERS:
        raise RuntimeError(f"unknown LLM provider '{provider_id}' in config.json")
    return PROVIDERS[provider_id]


def api_key(provider: Provider) -> str:
    key = keyring.get_password(config.CREDENTIAL_SERVICE, provider.credential)
    if not key:
        raise RuntimeError(f"no {provider.name} API key stored — onboarding hasn't completed")
    return key


def openai_client(provider: Provider, key: str | None = None) -> openai.OpenAI:
    return openai.OpenAI(api_key=key or api_key(provider), base_url=provider.base_url)


def llama_llm(provider: Provider | None = None):
    """A LlamaIndex LLM for the current provider (generation, explain, session
    notes)."""
    provider = provider or current()
    if provider.kind == "copilot":
        import copilot_llm

        return copilot_llm.CopilotLLM(model=provider.model, token=api_key(provider))

    from llama_index.core.base.llms.types import LLMMetadata
    from llama_index.llms.openai import OpenAI

    extra = {"extra_body": provider.extra_body} if provider.extra_body else {}
    if provider.context_window is None:
        return OpenAI(model=provider.model, api_key=api_key(provider), api_base=provider.base_url, additional_kwargs=extra)

    # What llama-index-llms-openai-like does, without that package: its
    # releases pin llama-index-llms-openai below the version used here.
    # OpenAI's own metadata raises on a model name it doesn't know, and its
    # tokenizer asks tiktoken, which doesn't know it either.
    context_window = provider.context_window

    class CompatibleOpenAI(OpenAI):
        @property
        def metadata(self) -> LLMMetadata:
            return LLMMetadata(
                context_window=context_window,
                num_output=self.max_tokens or -1,
                is_chat_model=True,
                is_function_calling_model=True,
                model_name=self.model,
            )

        @property
        def _tokenizer(self):
            return None

    return CompatibleOpenAI(model=provider.model, api_key=api_key(provider), api_base=provider.base_url, additional_kwargs=extra)
