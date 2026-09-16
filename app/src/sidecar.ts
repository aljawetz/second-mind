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

export interface Citation {
  source_type: "page" | "file" | "transcript" | "notes";
  label: string;
  item_id: string;
}

export type AskMode = "answer" | "socratic";

// main.py's /ask streams newline-delimited JSON over a chunked response:
// one {citations, grounded} line first (known once retrieval finishes,
// before the LLM starts), then one {delta} line per token, then {done}.
// Verified against a real index and a real strict HTTP client (Node's
// undici, close in rigor to Tauri's Rust reqwest) — chunked framing
// parses correctly through the plugin-http IPC bridge's ReadableStream.
export async function askQuestion(
  courseId: number,
  question: string,
  mode: AskMode,
  onEvent: (event: { citations?: Citation[]; grounded?: boolean; delta?: string; done?: boolean }) => void
): Promise<void> {
  const res = await fetch(`http://127.0.0.1:8756/courses/${courseId}/ask`, {
    method: "POST",
    body: JSON.stringify({ question, mode }),
  });

  if (!res.ok || !res.body) {
    const data = await res.json().catch(() => null);
    throw new Error(data?.error?.message ?? `ask failed (${res.status})`);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let newlineIndex;
    while ((newlineIndex = buffer.indexOf("\n")) !== -1) {
      const line = buffer.slice(0, newlineIndex);
      buffer = buffer.slice(newlineIndex + 1);
      if (line.trim()) onEvent(JSON.parse(line));
    }
  }
}

export interface Pointer {
  label: string;
  item_id: string;
}

export interface AssignmentExplanation {
  breakdown: string[];
  pointers: Pointer[];
}

// main.py's /explain — a single plain JSON response, not streamed like
// /ask: the breakdown step is one LLM call and the pointers step is
// retrieval-only (no synthesis), so there's nothing to render token by
// token (implementation-plan.md Step 10).
export async function explainAssignment(courseId: number, assignmentId: number): Promise<AssignmentExplanation> {
  const res = await fetch(`http://127.0.0.1:8756/courses/${courseId}/assignments/${assignmentId}/explain`, {
    method: "POST",
    body: JSON.stringify({}),
  });
  const data = await res.json();
  if (!res.ok) {
    throw new Error(data?.error?.message ?? `explain failed (${res.status})`);
  }
  return data;
}
