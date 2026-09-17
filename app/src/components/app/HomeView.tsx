import { useRef, useState } from "react";
import type { ArtifactType } from "../../types";
import { ARTIFACT_TYPES } from "../../data";
import { askQuestion, type AskMode, type CanvasAssignment, type Citation } from "../../sidecar";

interface ChatTurn {
  question: string;
  answer: string;
  citations: Citation[];
  grounded: boolean;
  status: "loading" | "streaming" | "done" | "error";
  error?: string;
}

function formatDue(dueAt: string | null): string {
  if (!dueAt) return "No due date";
  return new Date(dueAt).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function nextAssignment(assignments: CanvasAssignment[]): CanvasAssignment | null {
  if (assignments.length === 0) return null;
  const withDue = assignments.filter((a) => a.due_at);
  if (withDue.length === 0) return assignments[0];
  return [...withDue].sort((a, b) => new Date(a.due_at!).getTime() - new Date(b.due_at!).getTime())[0];
}

export default function HomeView({
  courseId,
  courseName,
  assignments,
  assignmentsError,
  socratic,
  onOpenArtifact,
  onOpenAssignment,
}: {
  courseId: number;
  courseName: string;
  assignments: CanvasAssignment[];
  assignmentsError: string | null;
  socratic: boolean;
  onOpenArtifact: (type: ArtifactType) => void;
  onOpenAssignment: (id: number) => void;
}) {
  const [askValue, setAskValue] = useState("");
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const threadRef = useRef<HTMLDivElement>(null);
  const upNext = nextAssignment(assignments);
  const lastTurn = turns[turns.length - 1];
  const busy = lastTurn?.status === "loading" || lastTurn?.status === "streaming";

  async function send() {
    const question = askValue.trim();
    if (!question || busy) return;
    setAskValue("");
    const turnIndex = turns.length;
    setTurns((prev) => [...prev, { question, answer: "", citations: [], grounded: false, status: "loading" }]);
    threadRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });

    const update = (patch: Partial<ChatTurn>) =>
      setTurns((prev) => prev.map((t, i) => (i === turnIndex ? { ...t, ...patch } : t)));

    try {
      const mode: AskMode = socratic ? "socratic" : "answer";
      await askQuestion(courseId, question, mode, (event) => {
        if (event.citations !== undefined) {
          update({ citations: event.citations, grounded: !!event.grounded, status: "streaming" });
        }
        if (event.delta) {
          setTurns((prev) => prev.map((t, i) => (i === turnIndex ? { ...t, answer: t.answer + event.delta } : t)));
        }
        if (event.done) {
          update({ status: "done" });
        }
      });
    } catch (err) {
      update({ status: "error", error: err instanceof Error ? err.message : "Something went wrong" });
    }
  }

  return (
    <section id="view-home">
      <div className="chat-panel">
        <div className="chat-head">Ask about this course</div>
        <div className="qa-thread" ref={threadRef}>
          {turns.length === 0 && <div className="qa-empty">Ask a question about this course to get started.</div>}
          {turns.map((turn, i) => (
            <div key={i}>
              <div className="qa-q">{turn.question}</div>
              {turn.status === "error" ? (
                <div className="qa-a qa-a-error">{turn.error}</div>
              ) : (
                <div className="qa-a">
                  {turn.status === "loading" ? (
                    <p className="qa-thinking">Thinking…</p>
                  ) : (
                    <>
                      <p>{turn.answer}</p>
                      {turn.grounded && turn.citations.length > 0 && (
                        <div className="qa-sources">
                          <span>Sources</span>
                          {turn.citations.map((c, ci) => (
                            <span className="cite" key={ci}>
                              {c.label}
                            </span>
                          ))}
                        </div>
                      )}
                    </>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
        <div className="ask-bar">
          <input
            type="text"
            placeholder="Ask about this course…"
            value={askValue}
            disabled={busy}
            onChange={(e) => setAskValue(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && send()}
          />
          <button className="ask-send" onClick={send} disabled={busy}>
            Ask
          </button>
        </div>
      </div>

      <div className="home-right">
        <div className="home-block">
          <div className="section-label">Next assignment</div>
          {assignmentsError && <div className="qa-a-error">{assignmentsError}</div>}
          {!assignmentsError && !upNext && <div className="qa-empty">No assignments found.</div>}
          {upNext && (
            <button className="assign-card" onClick={() => onOpenAssignment(upNext.id)}>
              <span className="main">
                <div className="ttl">{upNext.name}</div>
                <div className="crs">{courseName}</div>
              </span>
              <span className="pill pill-ochre">Due {formatDue(upNext.due_at)}</span>
              <span className="go">›</span>
            </button>
          )}
        </div>

        <div className="home-block">
          <div className="section-label">Study artifacts</div>
          <div className="artifact-row">
            {ARTIFACT_TYPES.map((t) => (
              <button className="artifact-btn" key={t.key} onClick={() => onOpenArtifact(t.key)}>
                <span className="lbl">{t.lbl}</span>
                <span className="sub">{t.sub}</span>
              </button>
            ))}
          </div>
        </div>

        <div className="home-block">
          <div className="section-label">Recent sessions</div>
          <div className="qa-empty">Session capture isn't built yet.</div>
        </div>
      </div>
    </section>
  );
}
