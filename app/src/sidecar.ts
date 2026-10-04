import { invoke } from "@tauri-apps/api/core";
import { fetch } from "@tauri-apps/plugin-http";
import type { LlmProvider } from "./credentials";

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

export type CredentialKind = "canvas" | LlmProvider;

// Format check only (Step 2) — not a real Canvas/model provider call yet. Step 3
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

// llm: whether the key for the provider config.json names is stored.
export interface CredentialsStatus {
  canvas: boolean;
  llm: boolean;
}

export async function getCredentialsStatus(): Promise<CredentialsStatus> {
  const res = await fetch("http://127.0.0.1:8756/credentials/status");
  return res.json();
}

// Sign in with GitHub for the Copilot provider (backend/github_signin.py,
// OAuth device flow): start gets a code to show, then poll once every
// `interval` seconds until it isn't "pending". On "done" the backend has
// already put the token in the Keychain; it never comes through here.
export interface GithubDeviceCode {
  user_code: string;
  verification_uri: string;
  interval: number;
  expires_in: number;
}

export interface GithubSignInPoll {
  status: "pending" | "done" | "denied" | "expired" | "error";
  interval?: number;
  login?: string | null;
  message?: string;
}

export async function startGithubSignIn(): Promise<GithubDeviceCode> {
  const res = await fetch("http://127.0.0.1:8756/github/device/start", { method: "POST", body: "{}" });
  const data = await res.json();
  if (!res.ok) {
    throw new Error(data?.error?.message ?? `couldn't start GitHub sign-in (${res.status})`);
  }
  return data;
}

export async function pollGithubSignIn(): Promise<GithubSignInPoll> {
  const res = await fetch("http://127.0.0.1:8756/github/device/poll", { method: "POST", body: "{}" });
  return res.json();
}

// config.json (data-model.md §3) — non-sensitive settings persisted by
// main.py at ~/.secondmind/config.json. Used at startup to skip onboarding for a
// returning user (real credentials + a remembered course list already on
// disk) instead of always starting fresh.
export interface SsbConfig {
  selected_courses?: number[];
  llm_provider?: LlmProvider;
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
//
// The backend saves every finished answer to a conversation. The first line
// carries its conversation_id; send it back as conversationId to continue
// that chat (the backend then reads the chat so far from disk and ignores
// history), or null to start a new one. With agent memory on, the
// {citations} line also lists memories_used: what the student told Second
// Mind in earlier chats that this answer drew on.
export interface MemoryUsed {
  id: string;
  text: string;
}

export interface AskEvent {
  conversation_id?: string;
  delta?: string;
  citations?: Citation[];
  grounded?: boolean;
  memories_used?: MemoryUsed[];
  error?: string;
  done?: boolean;
}

export async function askQuestion(
  courseId: number,
  courseName: string,
  question: string,
  history: { question: string; answer: string }[],
  conversationId: string | null,
  onEvent: (event: AskEvent) => void
): Promise<void> {
  const body = { question, history, course_name: courseName, ...(conversationId ? { conversation_id: conversationId } : {}) };
  const res = await fetch(`http://127.0.0.1:8756/courses/${courseId}/ask`, {
    method: "POST",
    body: JSON.stringify(body),
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

// Saved course chats (conversations.py): one per conversation id, newest
// first. A saved turn has no memories_used; only the live /ask stream does.
export interface ConversationSummary {
  conversation_id: string;
  title: string;
  updated_at: string;
  turn_count: number;
}

export interface SavedTurn {
  question: string;
  answer: string;
  citations: Citation[];
  grounded: boolean;
  asked_at: string;
}

export async function listConversations(courseId: number): Promise<ConversationSummary[]> {
  const res = await fetch(`http://127.0.0.1:8756/courses/${courseId}/conversations`);
  const data = await res.json();
  if (!res.ok) {
    throw new Error(data?.error?.message ?? `failed to list chats (${res.status})`);
  }
  return data.conversations ?? [];
}

export async function getConversation(
  courseId: number,
  conversationId: string
): Promise<{ conversation_id: string; title: string; turns: SavedTurn[] }> {
  const res = await fetch(`http://127.0.0.1:8756/courses/${courseId}/conversations/${conversationId}`);
  const data = await res.json();
  if (!res.ok) {
    throw new Error(data?.error?.message ?? `failed to open chat (${res.status})`);
  }
  return data;
}

// Also makes agent memory forget what it learned only from this chat.
export async function deleteConversation(courseId: number, conversationId: string): Promise<void> {
  const res = await fetch(`http://127.0.0.1:8756/courses/${courseId}/conversations/${conversationId}`, {
    method: "DELETE",
  });
  if (!res.ok) {
    const data = await res.json().catch(() => null);
    throw new Error(data?.error?.message ?? `failed to delete chat (${res.status})`);
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

export interface CourseMemory {
  id: string;
  kind: string;
  text: string;
  importance: number;
  event_time: string | null;
  created_at: string | null;
  valid_to: string | null;
  status: string;
}

export async function listMemories(courseId: number, includeInactive = false): Promise<CourseMemory[]> {
  const url = includeInactive
    ? `http://127.0.0.1:8756/courses/${courseId}/memories/all`
    : `http://127.0.0.1:8756/courses/${courseId}/memories`;
  const res = await fetch(url);
  const data = await res.json();
  if (!res.ok) {
    throw new Error(data?.error?.message ?? `failed to list memories (${res.status})`);
  }
  return data.memories ?? [];
}

export async function updateMemory(courseId: number, memoryId: string, text: string): Promise<CourseMemory> {
  // POST, not PATCH: Tauri's fetch builds a web Request() in WKWebView, which
  // rejects PATCH with "The string did not match the expected pattern."
  const res = await fetch(`http://127.0.0.1:8756/courses/${courseId}/memories/${memoryId}/edit`, {
    method: "POST",
    body: JSON.stringify({ text }),
  });
  const data = await res.json();
  if (!res.ok) {
    throw new Error(data?.error?.message ?? `failed to update memory (${res.status})`);
  }
  return data.memory;
}

export async function deleteMemory(courseId: number, memoryId: string): Promise<void> {
  const res = await fetch(`http://127.0.0.1:8756/courses/${courseId}/memories/${memoryId}`, { method: "DELETE" });
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    throw new Error(data?.error?.message ?? `failed to delete memory (${res.status})`);
  }
}

// Study artifacts (backend/study.py, docs/plans/2026-10-03-study-artifacts.md):
// quizzes and flashcards like NotebookLM's, written from the course's own
// indexed material. POST returns at once with status "generating"; poll the
// list or the artifact until it's "done" or "error".
export type StudyKind = "quiz" | "flashcards";
export type StudyCount = "fewer" | "standard" | "more";
export type StudyDifficulty = "easy" | "medium" | "hard";

export interface StudyOptions {
  count: StudyCount;
  difficulty: StudyDifficulty;
  topic: string;
  // Narrow to these indexed documents; null means the whole course.
  item_ids: string[] | null;
}

export const DEFAULT_STUDY_OPTIONS: StudyOptions = { count: "standard", difficulty: "medium", topic: "", item_ids: null };

export interface StudySummary {
  id: string;
  kind: StudyKind;
  title: string;
  status: "generating" | "done" | "error";
  error: string | null;
  created_at: string;
  options: StudyOptions;
  count: number;
}

export interface QuizOption {
  text: string;
  correct: boolean;
  rationale: string;
}

export interface QuizQuestion {
  question: string;
  options: QuizOption[];
  hint: string;
  citation: Citation;
  passage: string;
}

export interface Flashcard {
  front: string;
  back: string;
  citation: Citation;
  passage: string;
}

// The app's own record of where the student is; the backend only stores it.
export interface QuizProgress {
  // Question index → chosen option index.
  answers?: Record<string, number>;
  position?: number;
  finished?: boolean;
}

export interface FlashcardProgress {
  position?: number;
  marks?: Record<string, "got" | "missed">;
  removed?: number[];
  // Card indexes in the order being practised (shuffle, only-missed).
  order?: number[];
}

export interface StudyArtifact extends Omit<StudySummary, "count"> {
  items: (QuizQuestion | Flashcard)[];
  stats: { generated: number; unsourced: number; malformed: number; unsupported: number; checked: boolean } | null;
  progress: QuizProgress & FlashcardProgress;
}

export interface StudySource {
  item_id: string;
  source: string;
  source_type: Citation["source_type"];
  chunks: number;
  // Canvas's heading for it ("Week 02 - Literature Review", or the module's
  // name), or a kind ("Recorded sessions") for what Canvas doesn't list.
  group: string;
}

async function studyJson<T>(res: Response, what: string): Promise<T> {
  const data = await res.json().catch(() => null);
  if (!res.ok) throw new Error(data?.error?.message ?? `${what} failed (${res.status})`);
  return data as T;
}

export async function listStudy(courseId: number): Promise<StudySummary[]> {
  const res = await fetch(`http://127.0.0.1:8756/courses/${courseId}/study`);
  return (await studyJson<{ artifacts: StudySummary[] }>(res, "loading quizzes")).artifacts;
}

export async function listStudySources(courseId: number): Promise<StudySource[]> {
  const res = await fetch(`http://127.0.0.1:8756/courses/${courseId}/study/sources`);
  return (await studyJson<{ sources: StudySource[] }>(res, "loading sources")).sources;
}

export async function startStudy(courseId: number, kind: StudyKind, options: StudyOptions): Promise<StudySummary> {
  const res = await fetch(`http://127.0.0.1:8756/courses/${courseId}/study`, {
    method: "POST",
    body: JSON.stringify({ kind, ...options }),
  });
  return studyJson<StudySummary>(res, "generating");
}

export async function getStudy(courseId: number, id: string): Promise<StudyArtifact> {
  const res = await fetch(`http://127.0.0.1:8756/courses/${courseId}/study/${id}`);
  return studyJson<StudyArtifact>(res, "opening");
}

export async function saveStudyProgress(courseId: number, id: string, progress: StudyArtifact["progress"]): Promise<void> {
  const res = await fetch(`http://127.0.0.1:8756/courses/${courseId}/study/${id}/progress`, {
    method: "POST",
    body: JSON.stringify({ progress }),
  });
  await studyJson(res, "saving progress");
}

export async function deleteStudy(courseId: number, id: string): Promise<void> {
  const res = await fetch(`http://127.0.0.1:8756/courses/${courseId}/study/${id}`, { method: "DELETE" });
  await studyJson(res, "deleting");
}

// NotebookLM's "Download": the backend writes a CSV to ~/Downloads and says where.
export async function exportStudyCsv(courseId: number, id: string): Promise<string> {
  const res = await fetch(`http://127.0.0.1:8756/courses/${courseId}/study/${id}/export`, { method: "POST", body: "{}" });
  return (await studyJson<{ path: string }>(res, "saving the file")).path;
}
