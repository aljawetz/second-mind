import { useEffect, useState } from "react";
import { deleteSession, getSessionDetail, renameSession, type SessionDetail } from "../../sidecar";
import SessionContent from "./SessionContent";

export default function SessionDetailView({
  courseId,
  sessionId,
  onBack,
  onDeleted,
}: {
  courseId: number;
  sessionId: string;
  onBack: () => void;
  onDeleted: () => void;
}) {
  const [detail, setDetail] = useState<SessionDetail | null>(null);
  const [error, setError] = useState("");
  const [renaming, setRenaming] = useState(false);
  const [titleDraft, setTitleDraft] = useState("");

  useEffect(() => {
    let cancelled = false;
    getSessionDetail(courseId, sessionId)
      .then((d) => {
        if (!cancelled) {
          setDetail(d);
          setTitleDraft(d.title);
        }
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Couldn't load this session");
      });
    return () => {
      cancelled = true;
    };
  }, [courseId, sessionId]);

  async function handleRenameSave() {
    const title = titleDraft.trim();
    if (title && detail) {
      await renameSession(courseId, sessionId, title);
      setDetail({ ...detail, title });
    }
    setRenaming(false);
  }

  async function handleDelete() {
    if (!window.confirm(`Delete "${detail?.title ?? sessionId}"? This removes the transcript and notes permanently.`)) {
      return;
    }
    await deleteSession(courseId, sessionId);
    onDeleted();
  }

  return (
    <section id="view-new-session">
      <button className="back-link" onClick={onBack}>
        ‹ Course home
      </button>

      {error && <p className="qa-a-error">{error}</p>}

      {detail && (
        <>
          <div className="assign-head">
            {renaming ? (
              <input
                type="text"
                className="session-title-input"
                value={titleDraft}
                autoFocus
                onChange={(e) => setTitleDraft(e.target.value)}
                onBlur={handleRenameSave}
                onKeyDown={(e) => e.key === "Enter" && handleRenameSave()}
              />
            ) : (
              <h2 onClick={() => setRenaming(true)} title="Click to rename">
                {detail.title}
              </h2>
            )}
            <button className="icon-btn" title="Rename" aria-label="Rename" onClick={() => setRenaming(true)}>
              ✎
            </button>
            <button className="icon-btn" title="Delete session" aria-label="Delete session" onClick={handleDelete}>
              🗑
            </button>
          </div>

          {detail.status === "recording" || detail.status === "processing" ? (
            <p className="qa-thinking">Still processing…</p>
          ) : detail.status === "error" && !detail.summary ? (
            <p className="qa-a-error">{detail.error ?? "This recording couldn't be processed."}</p>
          ) : (
            <SessionContent transcript={detail.transcript} summary={detail.summary} />
          )}

          {detail.notes && (
            <div className="panel">
              <h3>Your notes</h3>
              <div className="assign-prompt">{detail.notes}</div>
            </div>
          )}
        </>
      )}
    </section>
  );
}
