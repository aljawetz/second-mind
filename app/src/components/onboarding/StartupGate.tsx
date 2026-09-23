import { useEffect, useState } from "react";
import { getBackendInstanceToken, pingSidecar } from "../../sidecar";
import LogoMark from "../LogoMark";

const POLL_MS = 2000;
const GRACE_MS = 5000; // switch to "first launch" copy after this long
const CEILING_MS = 240000; // 4 min — above the ~3.5 min worst case measured
// when macOS's Gatekeeper scans a never-before-seen build
// (implementation-plan.md Step 1). Already-scanned binaries respond in
// ~4s, so this only bites once per build.

export default function StartupGate({ onReady }: { onReady: () => void }) {
  const [message, setMessage] = useState("Getting things ready…");
  const [showRetry, setShowRetry] = useState(false);
  const [retryTick, setRetryTick] = useState(0);

  useEffect(() => {
    let cancelled = false;
    const startedAt = Date.now();
    setMessage("Getting things ready…");
    setShowRetry(false);

    function poll() {
      Promise.all([pingSidecar(), getBackendInstanceToken()])
        .then(([ping, token]) => {
          if (cancelled) return;
          if (ping.instance !== token) {
            // Something answered on 8756, but not the backend this launch
            // spawned (ours exits when its port is taken) — continuing would
            // silently run every request against stale code and state. No
            // Retry: our own backend already exited, so only a relaunch helps.
            setMessage("Another copy of Second Mind is already running. Quit it, then reopen Second Mind.");
            return;
          }
          onReady();
        })
        .catch(() => {
          if (cancelled) return;
          const elapsed = Date.now() - startedAt;
          if (elapsed > CEILING_MS) {
            setMessage("Couldn't reach the backend. This shouldn't happen after the first launch.");
            setShowRetry(true);
            return;
          }
          if (elapsed > GRACE_MS) {
            setMessage("First launch can take a minute or two while your Mac verifies the app — this only happens once.");
          }
          setTimeout(poll, POLL_MS);
        });
    }
    poll();

    return () => {
      cancelled = true;
    };
  }, [onReady, retryTick]);

  return (
    <div className="onboard onboard-loading">
      <div className="onboard-card">
        <div className="onboard-icon">
          <LogoMark size={26} />
        </div>
        <div>
          <h2 className="onboard-title">Starting up</h2>
          <p className="onboard-sub">{message}</p>
        </div>
        {showRetry && (
          <button className="btn-primary" onClick={() => setRetryTick((t) => t + 1)}>
            Retry
          </button>
        )}
      </div>
    </div>
  );
}
