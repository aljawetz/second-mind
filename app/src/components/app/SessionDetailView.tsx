import { useEffect, useRef, useState } from "react";
import { deleteSession, finalizeSession, getSessionDetail, renameSession, type SessionDetail } from "../../sidecar";
import SessionContent from "./SessionContent";

export default function SessionDetailView({
  courseId,
  sessionId,
  onBack,
  onDeleted,
  onStatusChange,
}: {
  courseId: number;
  sessionId: string;
  onBack: () => void;
  onDeleted: () => void;
  onStatusChange: () => void;
}) {
  const [detail, setDetail] = useState<SessionDetail | null>(null);
  const [error, setError] = useState("");
  const [renaming, setRenaming] = useState(false);
  const [titleDraft, setTitleDraft] = useState("");
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  // The parent passes a new function every render; a ref keeps the polling
  // interval below from restarting each time.
  const onStatusChangeRef = useRef(onStatusChange);
  onStatusChangeRef.current = onStatusChange;

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

  // A session being processed (just finalized, or opened mid-processing)
  // reloads itself until it finishes.
  useEffect(() => {
    if (detail?.status !== "processing") return;
    const id = setInterval(async () => {
      try {
        const next = await getSessionDetail(courseId, sessionId);
        if (next.status !== "processing") {
          setDetail(next);
          onStatusChangeRef.current();
        }
      } catch {
        // keep polling; the backend may be busy
      }
    }, 2000);
    return () => clearInterval(id);
  }, [detail?.status, courseId, sessionId]);

  async function handleFinalize() {
    if (!detail) return;
    setError("");
    try {
      await finalizeSession(courseId, sessionId);
      setDetail({ ...detail, status: "processing" });
      onStatusChange();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't finish this session");
    }
  }

  async function handleRenameSave() {
    const title = titleDraft.trim();
    if (title && detail) {
      await renameSession(courseId, sessionId, title);
      setDetail({ ...detail, title });
    }
    setRenaming(false);
  }

  async function handleDelete() {
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
            {confirmingDelete ? (
              <div className="session-actions manage-confirm">
                <span className="confirm-text">Delete the transcript and notes permanently?</span>
                <button className="btn-danger" onClick={() => void handleDelete()}>
                  Delete
                </button>
                <button className="icon-btn" onClick={() => setConfirmingDelete(false)}>
                  Cancel
                </button>
              </div>
            ) : (
              <div className="session-actions">
                <button className="icon-btn" title="Rename" aria-label="Rename" onClick={() => setRenaming(true)}>
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path>
                    <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path>
                  </svg>
                </button>
                <button className="icon-btn icon-btn-danger" title="Delete session" aria-label="Delete session" onClick={() => setConfirmingDelete(true)}>
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M3 6h18"></path>
                    <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
                    <line x1="10" y1="11" x2="10" y2="17"></line>
                    <line x1="14" y1="11" x2="14" y2="17"></line>
                  </svg>
                </button>
              </div>
            )}
          </div>

          {detail.status === "recording" || detail.status === "processing" ? (
            <p className="qa-thinking">Still processing…</p>
          ) : detail.status === "interrupted" ? (
            <div className="panel">
              <p>
                This recording was interrupted before it was stopped
                {detail.recorded_seconds ? `, but at least ${Math.max(1, Math.round(detail.recorded_seconds / 60))} min of it was saved` : ", but part of it was saved"}.
                You can still turn what was saved into a transcript and notes.
              </p>
              <button className="btn-primary" onClick={handleFinalize}>
                Finish processing
              </button>
            </div>
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
