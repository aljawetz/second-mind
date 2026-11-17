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

type Listener = (event: SyncEvent) => void;
type Fetch = (url: string, options: { method: string }) => Promise<Response>;

// React StrictMode replays effects during development. Subscribers share
// an active sync, including events emitted before the second effect mounted.
export function createSyncCourse(fetch: Fetch) {
  const active = new Map<number, { events: SyncEvent[]; listeners: Set<Listener>; completion: Promise<void> }>();

  async function read(courseId: number, emit: Listener) {
    let reader: ReadableStreamDefaultReader<Uint8Array> | undefined;
    try {
      const response = await fetch(`http://127.0.0.1:8756/courses/${courseId}/sync`, { method: "POST" });
      if (!response.ok || !response.body) {
        const data = await response.json().catch(() => null);
        throw new Error(data?.error?.message ?? `Sync failed (${response.status})`);
      }
      reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let terminal = false;
      function line(value: string) {
        if (!value.trim()) return;
        const event: SyncEvent = JSON.parse(value);
        terminal ||= event.done === true;
        emit(event);
      }
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let newline;
        while ((newline = buffer.indexOf("\n")) !== -1) {
          line(buffer.slice(0, newline));
          buffer = buffer.slice(newline + 1);
        }
      }
      line(buffer + decoder.decode());
      if (!terminal) throw new Error("Sync stopped before completion. The backend may have closed; check its terminal output and retry.");
    } catch (error) {
      await reader?.cancel().catch(() => {});
      // Tauri IPC often rejects with a string, rather than an Error object.
      throw error instanceof Error ? error : new Error(typeof error === "string" ? error : String(error));
    } finally {
      reader?.releaseLock();
    }
  }

  return async function syncCourse(courseId: number, onEvent: Listener): Promise<void> {
    let job = active.get(courseId);
    if (!job) {
      job = { events: [], listeners: new Set(), completion: Promise.resolve() };
      active.set(courseId, job);
      const current = job;
      job.completion = read(courseId, (event) => {
        current.events.push(event);
        for (const listener of current.listeners) listener(event);
      }).finally(() => active.delete(courseId));
    }
    for (const event of job.events) onEvent(event);
    job.listeners.add(onEvent);
    try {
      await job.completion;
    } finally {
      job.listeners.delete(onEvent);
    }
  };
}
