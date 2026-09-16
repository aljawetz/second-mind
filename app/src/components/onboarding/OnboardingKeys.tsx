import { useEffect, useState } from "react";
import { getCredential, setCredential } from "../../credentials";
import { validateCredential } from "../../sidecar";

export default function OnboardingKeys({ onNext }: { onNext: () => void }) {
  const [canvasKey, setCanvasKey] = useState("");
  const [openaiKey, setOpenaiKey] = useState("");
  const [canvasError, setCanvasError] = useState("");
  const [openaiError, setOpenaiError] = useState("");
  const [loaded, setLoaded] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    Promise.all([getCredential("canvas-token"), getCredential("openai-key")]).then(
      ([canvas, openai]) => {
        if (canvas) setCanvasKey(canvas);
        if (openai) setOpenaiKey(openai);
        setLoaded(true);
      }
    );
  }, []);

  const canProceed = loaded && !submitting && canvasKey.trim() !== "" && openaiKey.trim() !== "";

  async function handleConnect() {
    setSubmitting(true);
    setCanvasError("");
    setOpenaiError("");

    const [canvasResult, openaiResult] = await Promise.all([
      validateCredential("canvas", canvasKey),
      validateCredential("openai", openaiKey),
    ]);

    if (!canvasResult.valid || !openaiResult.valid) {
      if (!canvasResult.valid) setCanvasError(canvasResult.reason);
      if (!openaiResult.valid) setOpenaiError(openaiResult.reason);
      setSubmitting(false);
      return;
    }

    await Promise.all([
      setCredential("canvas-token", canvasKey),
      setCredential("openai-key", openaiKey),
    ]);
    setSubmitting(false);
    onNext();
  }

  return (
    <div className="onboard">
      <div className="onboard-card">
        <div className="onboard-icon">SSB</div>
        <div className="onboard-steps">
          <span className="onboard-dot active"></span>
          <span className="onboard-dot"></span>
          <span className="onboard-dot"></span>
        </div>
        <div>
          <h2 className="onboard-title">Connect your accounts</h2>
          <p className="onboard-sub">Keys stay on this device — SSB talks to Canvas and your model provider directly.</p>
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
            <span className="hint">canvas.cmu.edu → Account → Settings → New access token</span>
          )}
        </div>
        <div className="field">
          <label htmlFor="key-openai">OpenAI API key</label>
          <input
            type="password"
            id="key-openai"
            value={openaiKey}
            onChange={(e) => setOpenaiKey(e.target.value)}
          />
          {openaiError ? (
            <span className="field-error">{openaiError}</span>
          ) : (
            <span className="hint">platform.openai.com/api-keys</span>
          )}
        </div>
        <button className="btn-primary" disabled={!canProceed} onClick={handleConnect}>
          {submitting ? "Connecting…" : "Connect →"}
        </button>
      </div>
    </div>
  );
}
