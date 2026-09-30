import { open } from "@tauri-apps/plugin-shell";
import { useEffect, useRef, useState } from "react";
import { getCredential, LLM_PROVIDERS, type LlmProvider } from "../credentials";
import { getConfig, pollGithubSignIn, startGithubSignIn, type GithubDeviceCode } from "../sidecar";

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

function KeyField({ state }: { state: ProviderKeyState }) {
  const info = LLM_PROVIDERS[state.provider];
  return (
    <div className="field">
      <label htmlFor="key-llm">{info.keyLabel}</label>
      <input type="password" id="key-llm" value={state.key} onChange={(e) => state.setKey(e.target.value)} />
      {state.error ? <span className="field-error">{state.error}</span> : <span className="hint">{info.keyHint}</span>}
    </div>
  );
}

// Copilot: sign in through GitHub's device flow instead of making a token by
// hand. The backend stores the token; this then reads it back from the
// Keychain into the key field, so saving works the same as a pasted key.
function GithubSignIn({ state }: { state: ProviderKeyState }) {
  const [code, setCode] = useState<GithubDeviceCode | null>(null);
  const [login, setLogin] = useState<string | null | undefined>(undefined);
  const [manual, setManual] = useState(false);
  // Bumped by every new sign-in, cancel and unmount, so a stale poll loop
  // stops instead of racing the current one.
  const flow = useRef(0);

  useEffect(
    () => () => {
      flow.current += 1;
    },
    []
  );

  function fail(message: string) {
    setCode(null);
    state.setError(message);
  }

  function poll(id: number, interval: number) {
    setTimeout(async () => {
      if (flow.current !== id) return;
      const result = await pollGithubSignIn().catch(() => ({ status: "error" as const, message: "Lost touch with Second Mind's backend" }));
      if (flow.current !== id) return;
      if (result.status === "pending") {
        poll(id, result.interval ?? interval);
      } else if (result.status === "done") {
        setCode(null);
        setLogin(result.login ?? null);
        const token = await getCredential(LLM_PROVIDERS.copilot.credential);
        if (token) state.setKey(token);
      } else if (result.status === "denied") {
        fail("Sign-in was cancelled on GitHub.");
      } else if (result.status === "expired") {
        fail("The code expired — sign in again.");
      } else {
        fail(result.message ?? "GitHub sign-in failed");
      }
    }, interval * 1000);
  }

  async function signIn() {
    const id = ++flow.current;
    state.setError("");
    setLogin(undefined);
    try {
      const started = await startGithubSignIn();
      if (flow.current !== id) return;
      setCode(started);
      open(started.verification_uri).catch(() => {});
      poll(id, started.interval);
    } catch (err) {
      fail(err instanceof Error ? err.message : "Couldn't start GitHub sign-in");
    }
  }

  function cancel() {
    flow.current += 1;
    setCode(null);
  }

  return (
    <>
      <div className="field">
        <label>GitHub account</label>
        {code ? (
          <div className="signin-code">
            <span className="hint">Enter this code on GitHub and approve Second Mind:</span>
            <span className="signin-user-code">{code.user_code}</span>
            <span className="signin-actions">
              <button className="link-btn" onClick={() => open(code.verification_uri).catch(() => {})}>
                Open {code.verification_uri.replace("https://", "")}
              </button>
              <button className="link-btn" onClick={cancel}>
                Cancel
              </button>
            </span>
            <span className="hint">Waiting for approval…</span>
          </div>
        ) : (
          <>
            <button className="btn-secondary" onClick={signIn}>
              {state.key ? "Sign in again with GitHub" : "Sign in with GitHub"}
            </button>
            {login !== undefined ? (
              <span className="form-ok">Signed in{login ? ` as @${login}` : ""}.</span>
            ) : (
              <span className="hint">
                {state.key ? "A GitHub sign-in is saved." : "Uses your own Copilot plan (needs a Copilot subscription)."}
              </span>
            )}
          </>
        )}
        {state.error && !manual && <span className="field-error">{state.error}</span>}
      </div>
      <button className="link-btn" onClick={() => setManual((m) => !m)}>
        {manual ? "Hide the token field" : "Use a fine-grained token instead"}
      </button>
      {manual && <KeyField state={state} />}
    </>
  );
}

export default function ProviderKeyFields({ state }: { state: ProviderKeyState }) {
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
      {state.provider === "copilot" ? <GithubSignIn state={state} /> : <KeyField state={state} />}
    </>
  );
}
