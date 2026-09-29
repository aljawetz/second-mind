import { useEffect, useState } from "react";
import { getCredential, LLM_PROVIDERS, type LlmProvider } from "../credentials";
import { getConfig } from "../sidecar";

// Which model provider answers (config.json's llm_provider) and its key —
// shared by onboarding and Settings → Model provider. savedProvider is the
// one config.json names right now; provider is the one picked on screen.
export function useProviderKey() {
  const [provider, setProvider] = useState<LlmProvider>("openai");
  const [savedProvider, setSavedProvider] = useState<LlmProvider>("openai");
  const [key, setKey] = useState("");
  const [error, setError] = useState("");
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    getConfig().then((cfg) => {
      if (cfg.llm_provider && cfg.llm_provider in LLM_PROVIDERS) {
        setProvider(cfg.llm_provider);
        setSavedProvider(cfg.llm_provider);
      }
      setLoaded(true);
    });
  }, []);

  // Each provider's key lives in its own Keychain item: show whichever one
  // is already stored for the provider picked.
  useEffect(() => {
    let current = true;
    setKey("");
    setError("");
    getCredential(LLM_PROVIDERS[provider].credential).then((stored) => {
      if (current && stored) setKey(stored);
    });
    return () => {
      current = false;
    };
  }, [provider]);

  return { provider, setProvider, savedProvider, setSavedProvider, key, setKey, error, setError, loaded };
}

export type ProviderKeyState = ReturnType<typeof useProviderKey>;

export default function ProviderKeyFields({ state }: { state: ProviderKeyState }) {
  const info = LLM_PROVIDERS[state.provider];
  return (
    <>
      <div className="field">
        <label htmlFor="llm-provider">Model provider</label>
        <select id="llm-provider" value={state.provider} onChange={(e) => state.setProvider(e.target.value as LlmProvider)}>
          {(Object.keys(LLM_PROVIDERS) as LlmProvider[]).map((id) => (
            <option key={id} value={id}>
              {LLM_PROVIDERS[id].name}
            </option>
          ))}
        </select>
      </div>
      <div className="field">
        <label htmlFor="key-llm">{info.keyLabel}</label>
        <input type="password" id="key-llm" value={state.key} onChange={(e) => state.setKey(e.target.value)} />
        {state.error ? <span className="field-error">{state.error}</span> : <span className="hint">{info.keyHint}</span>}
      </div>
    </>
  );
}
