import { useCallback, useEffect, useState } from "react";
import { deleteMemory, listMemories, type CourseMemory } from "../../sidecar";

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
  const [includeInactive, setIncludeInactive] = useState(false);
  const [loadError, setLoadError] = useState("");
  const [actionError, setActionError] = useState("");
  const [forgettingId, setForgettingId] = useState<string | null>(null);

  const refresh = useCallback(() => {
    setLoadError("");
    return listMemories(courseId, includeInactive)
      .then(setMemories)
      .catch((err) => {
        setMemories([]);
        setLoadError(err instanceof Error ? err.message : "Couldn't load memories");
      });
  }, [courseId, includeInactive]);

  useEffect(() => {
    setMemories(null);
    refresh();
  }, [refresh]);

  async function handleForget(memory: CourseMemory) {
    setForgettingId(memory.id);
    setActionError("");
    try {
      await deleteMemory(courseId, memory.id);
      await refresh();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Couldn't forget this memory");
    } finally {
      setForgettingId(null);
    }
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
        <label className="manage-memories-filter">
          <input
            type="checkbox"
            checked={includeInactive}
            onChange={(e) => setIncludeInactive(e.target.checked)}
          />
          Show archived
        </label>
        {memories === null && !loadError && <p className="qa-thinking">Loading memories…</p>}
        {memories !== null && memories.length === 0 && !loadError && (
          <div className="qa-empty">Nothing saved yet — tell Second Mind something in chat and it may appear here.</div>
        )}
        {memories !== null && memories.length > 0 && (
          <div className="course-pick">
            {memories.map((m) => (
              <div className="course-row" key={m.id}>
                <span className="cmeta">
                  <div className="ccode">{m.text}</div>
                  <div className="cname">
                    {kindLabel(m.kind)}
                    {m.status !== "active" ? ` · ${m.status}` : ""}
                  </div>
                </span>
                <span className="manage-actions">
                  <button
                    className="icon-btn icon-btn-danger"
                    title="Forget — permanently removes this memory"
                    disabled={forgettingId === m.id}
                    onClick={() => handleForget(m)}
                  >
                    Forget
                  </button>
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </section>
  );
}
