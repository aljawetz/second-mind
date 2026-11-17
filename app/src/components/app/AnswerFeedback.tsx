import { useRef, useState } from "react";
import type { AnswerFeedback as Feedback } from "../../sidecar";

export default function AnswerFeedback({
  initialFeedback,
  onSave,
}: {
  initialFeedback?: Feedback | null;
  onSave: (rating: Feedback["rating"] | null, note: string) => Promise<Feedback | null>;
}) {
  const [feedback, setFeedback] = useState(initialFeedback ?? null);
  const [note, setNote] = useState(initialFeedback?.note ?? "");
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Also guard clicks before React has rendered the disabled controls.
  const pending = useRef(false);

  async function save(rating: Feedback["rating"] | null, nextNote: string) {
    if (pending.current) return;
    pending.current = true;
    setSaving(true);
    setError(null);
    try {
      const saved = await onSave(rating, nextNote);
      setFeedback(saved);
      setNote(saved?.note ?? "");
      setEditing(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't save feedback. Try again.");
    } finally {
      pending.current = false;
      setSaving(false);
    }
  }

  return (
    <div className="answer-feedback" aria-label="Answer feedback">
      <div className="qa-actions">
        {(["up", "down"] as const).map((rating) => (
          <button
            key={rating}
            type="button"
            aria-pressed={feedback?.rating === rating}
            disabled={saving}
            title={feedback?.rating === rating ? "Remove this rating" : undefined}
            onClick={() => void save(feedback?.rating === rating ? null : rating, feedback?.note ?? "")}
          >
            <svg viewBox="0 0 24 24" aria-hidden="true" className={rating === "down" ? "thumb-down" : undefined}>
              <path d="M7 10v11H3V10h4Zm0 0 5-8c2 0 3 1 2 5l-1 3h6a2 2 0 0 1 2 2l-2 7a3 3 0 0 1-3 2H7" />
            </svg>
            {rating === "up" ? "Helpful" : "Not helpful"}
          </button>
        ))}
        {feedback && !editing && (
          <button type="button" disabled={saving} onClick={() => { setNote(feedback.note); setEditing(true); }}>
            {feedback.note ? "Edit note" : "Add note"}
          </button>
        )}
        <span className="feedback-status" role="status">{saving ? "Saving…" : feedback ? "Saved on this computer" : ""}</span>
      </div>
      {editing && feedback && (
        <form className="feedback-note" onSubmit={(e) => { e.preventDefault(); void save(feedback.rating, note); }}>
          <label>
            Optional note
            <textarea value={note} maxLength={500} rows={2} disabled={saving} onChange={(e) => setNote(e.target.value)} />
          </label>
          <div className="qa-actions">
            <button type="submit" disabled={saving}>Save note</button>
            <button type="button" disabled={saving} onClick={() => { setNote(feedback.note); setEditing(false); setError(null); }}>Cancel</button>
            <span className="feedback-status">{note.length}/500</span>
          </div>
        </form>
      )}
      {!editing && feedback?.note && <p className="feedback-saved-note">{feedback.note}</p>}
      {error && <p className="qa-a-error" role="alert">{error}</p>}
    </div>
  );
}
