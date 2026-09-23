import { invoke } from "@tauri-apps/api/core";
import { fetch } from "@tauri-apps/plugin-http";

// Routed through the Rust backend via IPC, not the webview's own fetch:
// WKWebView blocks a plain fetch() to http://127.0.0.1 from this app's
// custom-scheme origin regardless of CORS headers, since the request never
// reaches the webview's network stack at all with this plugin.
export async function pingSidecar(): Promise<{ status: string; source: string; instance?: string }> {
  const res = await fetch("http://127.0.0.1:8756/ping");
  return res.json();
}

// The per-launch value lib.rs passed to the backend it spawned. A /ping
// answer carrying a different one (or none) came from a stale backend
// still holding port 8756, not ours.
export function getBackendInstanceToken(): Promise<string> {
  return invoke("backend_instance_token");
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

export interface CredentialsStatus {
  canvas: boolean;
  openai: boolean;
}

export async function getCredentialsStatus(): Promise<CredentialsStatus> {
  const res = await fetch("http://127.0.0.1:8756/credentials/status");
  return res.json();
}

// config.json (data-model.md §3) — non-sensitive settings persisted by
// main.py at ~/.secondmind/config.json. Used at startup to skip onboarding for a
// returning user (real credentials + a remembered course list already on
// disk) instead of always starting fresh.
export interface SsbConfig {
  selected_courses?: number[];
  llm_provider?: string;
  onboarding_complete?: boolean;
  canvas_base_url?: string;
}

export async function getConfig(): Promise<SsbConfig> {
  const res = await fetch("http://127.0.0.1:8756/config");
  return res.json();
}

export async function writeConfig(data: SsbConfig): Promise<SsbConfig> {
  const res = await fetch("http://127.0.0.1:8756/config", {
    method: "POST",
    body: JSON.stringify(data),
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

export interface CanvasAssignment {
  id: number;
  name: string;
  due_at: string | null;
  points_possible: number | null;
  description: string;
  // Real Canvas submission status (main.py's /courses/{id}/assignments,
  // include[]=submission) — not derived from due_at, so a late-but-turned-in
  // assignment or a not-yet-due one both come through correctly.
  submitted: boolean;
  late: boolean;
  missing: boolean;
}

export async function listAssignments(courseId: number): Promise<CanvasAssignment[]> {
  const res = await fetch(`http://127.0.0.1:8756/courses/${courseId}/assignments`);
  const data = await res.json();
  if (!res.ok) {
    throw new Error(data?.error?.message ?? `failed to list assignments (${res.status})`);
  }
  return data.assignments;
}

export interface Citation {
  source_type: "page" | "file" | "syllabus" | "assignment" | "transcript" | "notes";
  label: string;
  item_id: string;
}

// main.py's /ask streams newline-delimited JSON over a chunked response:
// {delta} lines as the answer is written, then one {citations, grounded}
// line (known only once the answer is done, since the model decides what to
// search and which results to cite), then {done}. An {error} line means the
// answer broke off after streaming started. Chunked framing verified earlier
// against a real strict HTTP client (Node's undici, close in rigor to
// Tauri's Rust reqwest) through the plugin-http IPC bridge's ReadableStream.
//
// history is the chat so far, oldest first, so follow-ups like "explain the
// second one" make sense. courseName goes into the model's instructions;
// the backend only stores course ids.
export interface AskEvent {
  delta?: string;
  citations?: Citation[];
  grounded?: boolean;
  error?: string;
  done?: boolean;
}

export async function askQuestion(
  courseId: number,
  courseName: string,
  question: string,
  history: { question: string; answer: string }[],
  onEvent: (event: AskEvent) => void
): Promise<void> {
  const res = await fetch(`http://127.0.0.1:8756/courses/${courseId}/ask`, {
    method: "POST",
    body: JSON.stringify({ question, history, course_name: courseName }),
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

export interface SyncEvent {
  item?: string;
  status?: "done" | "failed";
  error?: string;
  done?: boolean;
  new?: number;
  changed?: number;
  removed?: number;
  failed?: number;
}

// Same chunked-NDJSON contract as /ask (main.py's _write_chunk), just a
// different endpoint and event shape — the parsing loop is identical on
// purpose, not duplicated by accident.
export async function syncCourse(courseId: number, onEvent: (event: SyncEvent) => void): Promise<void> {
  const res = await fetch(`http://127.0.0.1:8756/courses/${courseId}/sync`, { method: "POST" });

  if (!res.ok || !res.body) {
    const data = await res.json().catch(() => null);
    throw new Error(data?.error?.message ?? `sync failed (${res.status})`);
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
  source_type: Citation["source_type"];
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

// Session capture (implementation-plan.md Step 12, design spec §9.3).
// Recording itself happens here in the frontend (getUserMedia +
// MediaRecorder) — the backend only handles what comes after stop.
export type SessionRunStatus = "recording" | "processing" | "done" | "error";

export interface SessionSummary {
  session_id: string;
  title: string;
  status: SessionRunStatus;
  class_num: number | null;
}

export interface SessionDetail extends SessionSummary {
  transcript?: string;
  summary?: string;
  notes?: string;
  error?: string;
}

export async function startSession(
  courseId: number
): Promise<{ session_id: string; status: string; class_num: number; title: string }> {
  const res = await fetch(`http://127.0.0.1:8756/courses/${courseId}/sessions/start`, { method: "POST" });
  return res.json();
}

// Raw audio bytes as the body (audio/mp4 from MediaRecorder) — not
// JSON/base64, this backend already reads raw request bodies elsewhere.
export async function stopSession(sessionId: string, audioBlob: Blob): Promise<{ session_id: string; status: string }> {
  const res = await fetch(`http://127.0.0.1:8756/sessions/${sessionId}/stop`, {
    method: "POST",
    body: audioBlob,
  });
  return res.json();
}

export async function saveSessionNotes(sessionId: string, text: string): Promise<void> {
  await fetch(`http://127.0.0.1:8756/sessions/${sessionId}/notes`, {
    method: "POST",
    body: JSON.stringify({ text }),
  });
}

export async function listSessions(courseId: number): Promise<SessionSummary[]> {
  const res = await fetch(`http://127.0.0.1:8756/courses/${courseId}/sessions`);
  const data = await res.json();
  return data.sessions;
}

// Disk-backed, not just the in-memory status the backend tracks while
// actively recording/processing — this is also how a past session (from
// a previous app run) gets viewed, not just how an active one is polled.
export async function getSessionDetail(courseId: number, sessionId: string): Promise<SessionDetail> {
  const res = await fetch(`http://127.0.0.1:8756/courses/${courseId}/sessions/${sessionId}`);
  return res.json();
}

export async function renameSession(courseId: number, sessionId: string, title: string): Promise<void> {
  await fetch(`http://127.0.0.1:8756/courses/${courseId}/sessions/${sessionId}/rename`, {
    method: "POST",
    body: JSON.stringify({ title }),
  });
}

export async function deleteSession(courseId: number, sessionId: string): Promise<void> {
  await fetch(`http://127.0.0.1:8756/courses/${courseId}/sessions/${sessionId}`, { method: "DELETE" });
}

// Course removal (implementation-plan.md Step 13) — two structurally
// distinct actions, not one endpoint with a flag. unselect only touches
// config.json; delete is the real destructive path (LanceDB table,
// manifest, every session recording and note — all of it, unrecoverable).
export async function unselectCourse(courseId: number): Promise<void> {
  await fetch(`http://127.0.0.1:8756/courses/${courseId}/unselect`, { method: "POST" });
}

export async function deleteCourse(courseId: number): Promise<void> {
  await fetch(`http://127.0.0.1:8756/courses/${courseId}`, { method: "DELETE" });
}
