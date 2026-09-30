import { useEffect, useState } from "react";
import { LLM_PROVIDERS, setCredential } from "../../credentials";
import { validateCredential, writeConfig } from "../../sidecar";
import ProviderKeyFields, { useProviderKey } from "../ProviderKeyFields";

// Settings → Model provider: switch provider or replace a key after
// onboarding. The backend reads config.json's llm_provider on every model
// call (providers.current()), so the next question already uses the new one
// — no restart.
export default function ModelProviderView({ onBack }: { onBack: () => void }) {
  const state = useProviderKey();
  const [saving, setSaving] = useState(false);
  const [savedMessage, setSavedMessage] = useState("");
  const { provider, key } = state;

  useEffect(() => {
    setSavedMessage("");
  }, [provider, key]);

  async function handleSave() {
    setSaving(true);
    state.setError("");
    try {
      const result = await validateCredential(provider, key);
      if (!result.valid) {
        state.setError(result.reason);
        return;
      }
      await setCredential(LLM_PROVIDERS[provider].credential, key);
      await writeConfig({ llm_provider: provider });
      state.setSavedProvider(provider);
      setSavedMessage(`Saved. New questions use ${LLM_PROVIDERS[provider].name}.`);
    } catch (err) {
      state.setError(err instanceof Error ? err.message : "Couldn't save the provider");
    } finally {
      setSaving(false);
    }
  }

  return (
    <section id="view-model-provider">
      <button className="back-link" onClick={onBack}>
        ‹ Course home
      </button>
      <p className="qa-empty manage-memories-intro">
        Second Mind answers with <strong>{LLM_PROVIDERS[state.savedProvider].name}</strong>. Keys stay in this Mac's
        Keychain, one per provider, so switching back doesn't lose a key.
      </p>

      <div className="home-block model-provider-form">
        <div className="section-label">Model provider</div>
        <ProviderKeyFields state={state} />
        <div className="model-provider-actions">
          <button className="btn-primary" disabled={!state.loaded || saving || key.trim() === ""} onClick={handleSave}>
            {saving ? "Saving…" : "Save"}
          </button>
          {savedMessage && <span className="form-ok">{savedMessage}</span>}
        </div>
      </div>
    </section>
  );
}
