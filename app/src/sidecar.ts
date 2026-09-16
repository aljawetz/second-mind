import { fetch } from "@tauri-apps/plugin-http";

// Routed through the Rust backend via IPC, not the webview's own fetch:
// WKWebView blocks a plain fetch() to http://127.0.0.1 from this app's
// custom-scheme origin regardless of CORS headers, since the request never
// reaches the webview's network stack at all with this plugin.
export async function pingSidecar(): Promise<{ status: string; source: string }> {
  const res = await fetch("http://127.0.0.1:8756/ping");
  return res.json();
}
