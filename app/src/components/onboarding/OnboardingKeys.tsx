import { useEffect, useState } from "react";
import { getCredential, setCredential } from "../../credentials";
import { getConfig, validateCredential, writeConfig } from "../../sidecar";
import LogoMark from "../LogoMark";

// canvasUrl comes back from onNext already normalized (config.py's
// normalize_canvas_base_url, applied server-side on write) rather than
// whatever raw form the student typed — contribution-and-distribution-
// plan.md step 2, SSB used to only work against canvas.cmu.edu.
export default function OnboardingKeys({ onNext }: { onNext: (canvasUrl: string) => void }) {
  const [canvasUrl, setCanvasUrl] = useState("");
  const [canvasKey, setCanvasKey] = useState("");
  const [openaiKey, setOpenaiKey] = useState("");
  const [canvasError, setCanvasError] = useState("");
  const [openaiError, setOpenaiError] = useState("");
  const [loaded, setLoaded] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    Promise.all([getCredential("canvas-token"), getCredential("openai-key"), getConfig()]).then(
      ([canvas, openai, cfg]) => {
        if (canvas) setCanvasKey(canvas);
        if (openai) setOpenaiKey(openai);
        if (cfg.canvas_base_url) setCanvasUrl(cfg.canvas_base_url);
        setLoaded(true);
      }
    );
  }, []);

  const canProceed =
    loaded && !submitting && canvasUrl.trim() !== "" && canvasKey.trim() !== "" && openaiKey.trim() !== "";

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

    const [, , savedConfig] = await Promise.all([
      setCredential("canvas-token", canvasKey),
      setCredential("openai-key", openaiKey),
      writeConfig({ canvas_base_url: canvasUrl }),
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
          <p className="onboard-sub">Keys stay on this device — SSB talks to Canvas and your model provider directly.</p>
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
