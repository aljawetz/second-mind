import { useEffect, useState } from "react";
import { getCredential, LLM_PROVIDERS, setCredential, type LlmProvider } from "../../credentials";
import { getConfig, validateCredential, writeConfig } from "../../sidecar";
import LogoMark from "../LogoMark";

// canvasUrl comes back from onNext already normalized (config.py's
// normalize_canvas_base_url, applied server-side on write) rather than
// whatever raw form the student typed — contribution-and-distribution-
// plan.md step 2, Second Mind used to only work against canvas.cmu.edu.
export default function OnboardingKeys({ onNext }: { onNext: (canvasUrl: string) => void }) {
  const [canvasUrl, setCanvasUrl] = useState("");
  const [canvasKey, setCanvasKey] = useState("");
  const [provider, setProvider] = useState<LlmProvider>("openai");
  const [llmKey, setLlmKey] = useState("");
  const [canvasError, setCanvasError] = useState("");
  const [llmError, setLlmError] = useState("");
  const [loaded, setLoaded] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const providerInfo = LLM_PROVIDERS[provider];

  useEffect(() => {
    Promise.all([getCredential("canvas-token"), getConfig()]).then(([canvas, cfg]) => {
      if (canvas) setCanvasKey(canvas);
      if (cfg.canvas_base_url) setCanvasUrl(cfg.canvas_base_url);
      if (cfg.llm_provider && cfg.llm_provider in LLM_PROVIDERS) setProvider(cfg.llm_provider);
      setLoaded(true);
    });
  }, []);

  // Each provider's key lives in its own Keychain item: show whichever one
  // is already stored for the provider picked.
  useEffect(() => {
    let current = true;
    setLlmKey("");
    setLlmError("");
    getCredential(LLM_PROVIDERS[provider].credential).then((key) => {
      if (current && key) setLlmKey(key);
    });
    return () => {
      current = false;
    };
  }, [provider]);

  const canProceed =
    loaded && !submitting && canvasUrl.trim() !== "" && canvasKey.trim() !== "" && llmKey.trim() !== "";

  async function handleConnect() {
    setSubmitting(true);
    setCanvasError("");
    setLlmError("");

    const [canvasResult, llmResult] = await Promise.all([
      validateCredential("canvas", canvasKey),
      validateCredential(provider, llmKey),
    ]);

    if (!canvasResult.valid || !llmResult.valid) {
      if (!canvasResult.valid) setCanvasError(canvasResult.reason);
      if (!llmResult.valid) setLlmError(llmResult.reason);
      setSubmitting(false);
      return;
    }

    const [, , savedConfig] = await Promise.all([
      setCredential("canvas-token", canvasKey),
      setCredential(providerInfo.credential, llmKey),
      writeConfig({ canvas_base_url: canvasUrl, llm_provider: provider }),
    ]);
    setSubmitting(false);
    onNext(savedConfig.canvas_base_url ?? canvasUrl);
  }

  return (
    <div className="onboard">
      <div className="onboard-card">
        <div className="onboard-icon">
          <LogoMark size={26} />
        </div>
        <div className="onboard-steps">
          <span className="onboard-dot active"></span>
          <span className="onboard-dot"></span>
          <span className="onboard-dot"></span>
        </div>
        <div>
          <h2 className="onboard-title">Connect your accounts</h2>
          <p className="onboard-sub">Keys stay on this device — Second Mind talks to Canvas and your model provider directly.</p>
        </div>
        <div className="field">
          <label htmlFor="canvas-url">Your school's Canvas URL</label>
          <input
            type="text"
            id="canvas-url"
            placeholder="canvas.cmu.edu"
            value={canvasUrl}
            onChange={(e) => setCanvasUrl(e.target.value)}
          />
          <span className="hint">The Canvas address you already use to log in — e.g. canvas.cmu.edu</span>
        </div>
        <div className="field">
          <label htmlFor="key-canvas">Canvas API token</label>
          <input
            type="password"
            id="key-canvas"
            value={canvasKey}
            onChange={(e) => setCanvasKey(e.target.value)}
          />
          {canvasError ? (
            <span className="field-error">{canvasError}</span>
          ) : (
            <span className="hint">Your Canvas → Account → Settings → New access token</span>
          )}
        </div>
        <div className="field">
          <label htmlFor="llm-provider">Model provider</label>
          <select id="llm-provider" value={provider} onChange={(e) => setProvider(e.target.value as LlmProvider)}>
            {(Object.keys(LLM_PROVIDERS) as LlmProvider[]).map((id) => (
              <option key={id} value={id}>
                {LLM_PROVIDERS[id].name}
              </option>
            ))}
          </select>
        </div>
        <div className="field">
          <label htmlFor="key-llm">{providerInfo.keyLabel}</label>
          <input
            type="password"
            id="key-llm"
            value={llmKey}
            onChange={(e) => setLlmKey(e.target.value)}
          />
          {llmError ? (
            <span className="field-error">{llmError}</span>
          ) : (
            <span className="hint">{providerInfo.keyHint}</span>
          )}
        </div>
        <button className="btn-primary" disabled={!canProceed} onClick={handleConnect}>
          {submitting ? "Connecting…" : "Connect →"}
        </button>
      </div>
    </div>
  );
}
