import { useState } from "react";

export default function OnboardingKeys({ onNext }: { onNext: () => void }) {
  const [canvasKey, setCanvasKey] = useState("7f2ad9c1e0b3a5f6d2c8e1b4a9f0d3c7");
  const [openaiKey, setOpenaiKey] = useState("sk-live-9f3ad1c8b2e6f0a4d7c9b1e3f5a8d0c2");
  const canProceed = canvasKey.trim() !== "" && openaiKey.trim() !== "";

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
          <span className="hint">canvas.cmu.edu → Account → Settings → New access token</span>
        </div>
        <div className="field">
          <label htmlFor="key-openai">OpenAI API key</label>
          <input
            type="password"
            id="key-openai"
            value={openaiKey}
            onChange={(e) => setOpenaiKey(e.target.value)}
          />
          <span className="hint">platform.openai.com/api-keys</span>
        </div>
        <button className="btn-primary" disabled={!canProceed} onClick={onNext}>
          Connect →
        </button>
      </div>
    </div>
  );
}
