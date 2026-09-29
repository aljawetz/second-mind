import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./styles.css";

const isMac = navigator.userAgent.includes("Macintosh");

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    {/* macOS renders the traffic-light buttons as an overlay (tauri.conf.json
        titleBarStyle: "Overlay") straight onto the webview, with no native
        bar of its own — this strip is what actually sits behind them, so it
        needs its own background and an explicit drag region to keep the
        window movable. Windows keeps its native title bar (see
        tauri.macos.conf.json), so the strip is macOS-only. */}
    {isMac && <div id="titlebar-drag" data-tauri-drag-region></div>}
    <div id="app-content">
      <App />
    </div>
  </React.StrictMode>
);
