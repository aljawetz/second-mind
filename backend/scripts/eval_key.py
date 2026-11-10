"""Evaluation scripts spend on their own OpenAI key when one is stored.

The app's key sits in the Keychain as "openai-key". A second item,
"openai-eval-key", is for evaluations only, so test spending can have its
own limit and never touches the key the app runs on. Store it with the key
on the clipboard (the `security` prompt cuts input at 128 characters):

    security add-generic-password -U -s com.secondmind.app -a openai-eval-key -w "$(pbpaste)"

Without that item, scripts use the app's key as before.
"""

import credentials
import providers

EVAL_KEY = "openai-eval-key"


def use_eval_key() -> bool:
    """Call once at the start of a script. From then on every OpenAI call
    made through providers (clients, OpenAIProvider, the judge) uses the
    evaluation key. False when none is stored and the app's key stays."""
    key = credentials.get(EVAL_KEY)
    if not key:
        return False
    stored = credentials.get

    def get(name: str) -> str | None:
        return key if name == providers.OPENAI.credential else stored(name)

    credentials.get = get
    return True
