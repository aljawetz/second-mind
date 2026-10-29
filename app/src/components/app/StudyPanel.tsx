import { useState } from "react";
import { DEFAULT_STUDY_OPTIONS, type StudyKind, type StudyOptions, type StudySummary } from "../../sidecar";
import StudyCustomize from "./StudyCustomize";

// Course home's Study panel, like NotebookLM's Studio: a tile per kind that
// generates with the default options, a pencil on each for choosing them,
// and everything generated so far, newest first.

const KIND_LABEL: Record<StudyKind, string> = { quiz: "Quiz", flashcards: "Flashcards" };

function describe(a: StudySummary): string {
  if (a.status === "generating") return "Generating…";
  if (a.status === "error") return a.error ?? "Couldn't generate";
  const n = `${a.count} ${a.kind === "quiz" ? (a.count === 1 ? "question" : "questions") : a.count === 1 ? "card" : "cards"}`;
  return `${n} · ${a.options.difficulty[0].toUpperCase()}${a.options.difficulty.slice(1)}`;
}

export default function StudyPanel({
  courseId,
  artifacts,
  error,
  onCreate,
  onOpen,
  onDelete,
}: {
  courseId: number;
  artifacts: StudySummary[];
  error: string | null;
  onCreate: (kind: StudyKind, options: StudyOptions) => Promise<void>;
  onOpen: (id: string) => void;
  onDelete: (id: string) => Promise<void>;
}) {
  const [customizing, setCustomizing] = useState<StudyKind | null>(null);
  const [createError, setCreateError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  function confirm(id: string | null) {
    setDeleteError(null);
    setConfirming(id);
  }

  async function create(kind: StudyKind, options: StudyOptions) {
    setCreateError(null);
    try {
      await onCreate(kind, options);
    } catch (err) {
      setCreateError(err instanceof Error ? err.message : "Couldn't start generating");
    }
  }

  async function remove(id: string) {
    setDeleting(true);
    setDeleteError(null);
    try {
      await onDelete(id);
      setConfirming(null);
    } catch (err) {
      // The row stays, and the confirm stays open to try again.
      setDeleteError(err instanceof Error && err.message ? err.message : "Couldn't delete");
    } finally {
      setDeleting(false);
    }
  }

  return (
    <section className="study-panel" aria-label="Study">
      <div className="assign-top">
        <h2>Study</h2>
      </div>
      <div className="study-kinds">
        {(["quiz", "flashcards"] as StudyKind[]).map((kind) => (
          <div className="study-kind-row" key={kind}>
            <span className="ttl">{KIND_LABEL[kind]}</span>
            <button
              type="button"
              className="text-btn"
              aria-label={`Customize ${KIND_LABEL[kind].toLowerCase()}`}
              onClick={() => setCustomizing(kind)}
            >
              Customize
            </button>
            <button type="button" className="btn-secondary btn-small" onClick={() => void create(kind, DEFAULT_STUDY_OPTIONS)}>
              Create
            </button>
          </div>
        ))}
      </div>
      <div className="assign-body study-list">
        {(createError || error) && <p className="qa-a-error">{createError ?? error}</p>}
        {!error && artifacts.length === 0 && (
          <p className="qa-empty">Quizzes and flashcards you make from this course's material show up here.</p>
        )}
        {artifacts.map((a) =>
          confirming === a.id ? (
            <div className="side-confirm study-confirm" key={a.id}>
              <span>Delete “{a.title}”?</span>
              {deleteError && (
                <span className="study-confirm-error" role="alert">
                  {deleteError}
                </span>
              )}
              <button type="button" className="btn-danger" disabled={deleting} onClick={() => void remove(a.id)}>
                Delete
              </button>
              <button type="button" className="icon-btn" disabled={deleting} onClick={() => confirm(null)}>
                Cancel
              </button>
            </div>
          ) : (
            <div className="side-row study-row" key={a.id}>
              <button
                type="button"
                className={"study-open" + (a.status === "error" ? " failed" : "")}
                disabled={a.status !== "done"}
                onClick={() => onOpen(a.id)}
              >
                <span className="body">
                  <span className="ttl">{a.title}</span>
                  <span className="meta">
                    {a.status === "generating" && <span className="session-status-dot" aria-hidden="true"></span>}
                    {describe(a)}
                  </span>
                </span>
              </button>
              {a.status !== "generating" && (
                <button
                  type="button"
                  className="side-del"
                  aria-label={`Delete ${a.title}`}
                  title="Delete"
                  onClick={() => confirm(a.id)}
                >
                  <svg viewBox="0 0 24 24" aria-hidden="true">
                    <path d="M3 6h18M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                  </svg>
                </button>
              )}
            </div>
          )
        )}
      </div>
      {customizing && (
        <StudyCustomize
          courseId={courseId}
          kind={customizing}
          onCancel={() => setCustomizing(null)}
          onGenerate={(options) => {
            const kind = customizing;
            setCustomizing(null);
            void create(kind, options);
          }}
        />
      )}
    </section>
  );
}
