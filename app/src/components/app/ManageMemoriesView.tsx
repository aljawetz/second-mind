import { useCallback, useEffect, useState } from "react";
import { deleteMemory, listMemories, updateMemory, type CourseMemory } from "../../sidecar";

function kindLabel(kind: string): string {
  if (kind === "fact") return "Fact";
  if (kind === "preference") return "Preference";
  if (kind === "event") return "Event";
  if (kind === "summary") return "Chat summary";
  return kind;
}

export default function ManageMemoriesView({
  courseId,
  courseCode,
  courseName,
  onBack,
}: {
  courseId: number;
  courseCode: string;
  courseName: string;
  onBack: () => void;
}) {
  const [memories, setMemories] = useState<CourseMemory[] | null>(null);
  const [loadError, setLoadError] = useState("");
  const [actionError, setActionError] = useState("");
  const [forgettingId, setForgettingId] = useState<string | null>(null);
  const [confirmingForgetId, setConfirmingForgetId] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editDraft, setEditDraft] = useState("");
  const [savingId, setSavingId] = useState<string | null>(null);

  const refresh = useCallback(() => {
    setLoadError("");
    return listMemories(courseId)
      .then(setMemories)
      .catch((err) => {
        setMemories([]);
        setLoadError(err instanceof Error ? err.message : "Couldn't load memories");
      });
  }, [courseId]);

  useEffect(() => {
    setMemories(null);
    setEditingId(null);
    refresh();
  }, [refresh]);

  async function handleForget(memory: CourseMemory) {
    setForgettingId(memory.id);
    setActionError("");
    try {
      await deleteMemory(courseId, memory.id);
      if (editingId === memory.id) setEditingId(null);
      setConfirmingForgetId(null);
      await refresh();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Couldn't forget this memory");
    } finally {
      setForgettingId(null);
    }
  }

  function startEdit(memory: CourseMemory) {
    setActionError("");
    setConfirmingForgetId(null);
    setEditingId(memory.id);
    setEditDraft(memory.text);
  }

  async function saveEdit(memoryId: string) {
    const text = editDraft.trim();
    if (!text) {
      setActionError("Memory text can't be empty.");
      return;
    }
    setSavingId(memoryId);
    setActionError("");
    try {
      await updateMemory(courseId, memoryId, text);
      setEditingId(null);
      await refresh();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Couldn't save this memory");
    } finally {
      setSavingId(null);
    }
  }

  function cancelEdit() {
    setEditingId(null);
    setEditDraft("");
  }

  function renderMemoryRow(m: CourseMemory) {
    const editing = editingId === m.id;

    return (
      <div className="course-row" key={m.id}>
        <span className="cmeta">
          {editing ? (
            <textarea
              className="memory-edit-area"
              value={editDraft}
              autoFocus
              rows={3}
              onChange={(e) => setEditDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Escape") cancelEdit();
                if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) void saveEdit(m.id);
              }}
            />
          ) : (
            <div className="ccode">{m.text}</div>
          )}
          <div className="cname">{kindLabel(m.kind)}</div>
        </span>
        <span className="manage-actions">
          {editing ? (
            <>
              <button
                className="icon-btn"
                disabled={savingId === m.id}
                onClick={() => void saveEdit(m.id)}
              >
                Save
              </button>
              <button className="icon-btn" disabled={savingId === m.id} onClick={cancelEdit}>
                Cancel
              </button>
            </>
          ) : confirmingForgetId === m.id ? (
            <span className="manage-confirm">
              <button
                className="btn-danger"
                disabled={forgettingId === m.id}
                onClick={() => void handleForget(m)}
              >
                Confirm forget
              </button>
              <button
                className="icon-btn"
                disabled={forgettingId === m.id}
                onClick={() => setConfirmingForgetId(null)}
              >
                Cancel
              </button>
            </span>
          ) : (
            <>
              <button className="icon-btn" title="Edit memory text" onClick={() => startEdit(m)}>
                Edit
              </button>
              <button
                className="icon-btn icon-btn-danger"
                title="Forget — permanently removes this memory"
                disabled={forgettingId === m.id}
                onClick={() => setConfirmingForgetId(m.id)}
              >
                Forget
              </button>
            </>
          )}
        </span>
      </div>
    );
  }

  return (
    <section id="view-manage-memories">
      <button className="back-link" onClick={onBack}>
        ‹ Course home
      </button>
      <p className="qa-empty manage-memories-intro">
        What Second Mind remembers for <strong>{courseCode}</strong>
        {courseName ? ` · ${courseName}` : ""}. These details can shape answers in new chats. Forgetting
        removes them permanently.
      </p>
      {loadError && <p className="qa-a-error">{loadError}</p>}
      {actionError && <p className="qa-a-error">{actionError}</p>}

      <div className="home-block">
        <div className="section-label">Saved memories</div>
        {memories === null && !loadError && <p className="qa-thinking">Loading memories…</p>}
        {memories !== null && memories.length === 0 && !loadError && (
          <div className="qa-empty">Nothing saved yet — tell Second Mind something in chat and it may appear here.</div>
        )}
        {memories !== null && memories.length > 0 && (
          <div className="course-pick">{memories.map(renderMemoryRow)}</div>
        )}
      </div>
    </section>
  );
}
