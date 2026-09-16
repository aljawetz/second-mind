import { fetch } from "@tauri-apps/plugin-http";

// Routed through the Rust backend via IPC, not the webview's own fetch:
// WKWebView blocks a plain fetch() to http://127.0.0.1 from this app's
// custom-scheme origin regardless of CORS headers, since the request never
// reaches the webview's network stack at all with this plugin.
export async function pingSidecar(): Promise<{ status: string; source: string }> {
  const res = await fetch("http://127.0.0.1:8756/ping");
  return res.json();
}

export type CredentialKind = "canvas" | "openai";

// Format check only (Step 2) — not a real Canvas/OpenAI call yet. Step 3
// upgrades main.py's handler for this same endpoint to do that; the
// frontend's interface here doesn't need to change when it does.
export async function validateCredential(
  kind: CredentialKind,
  value: string
): Promise<{ valid: boolean; reason: string }> {
  const res = await fetch("http://127.0.0.1:8756/credentials/validate", {
    method: "POST",
    body: JSON.stringify({ kind, value }),
  });
  return res.json();
}

export interface CanvasCourse {
  id: number;
  code: string | null;
  name: string;
}

// Error shape per overview.md's documented contract:
// { error: { code, message, detail? } }
export async function listCourses(): Promise<CanvasCourse[]> {
  const res = await fetch("http://127.0.0.1:8756/courses");
  const data = await res.json();
  if (!res.ok) {
    throw new Error(data?.error?.message ?? `failed to list courses (${res.status})`);
  }
  return data.courses;
}
