import { useRef, useState } from "react";
import type { ArtifactType, Course } from "../../types";
import { ARTIFACT_TYPES } from "../../data";
import { askQuestion, type AskMode, type Citation } from "../../sidecar";

interface ChatTurn {
  question: string;
  answer: string;
  citations: Citation[];
  grounded: boolean;
  status: "loading" | "streaming" | "done" | "error";
  error?: string;
}

export default function HomeView({
  course,
  courseCode,
  courseId,
  socratic,
  onOpenSession,
  onOpenArtifact,
  onOpenAssignment,
}: {
  course: Course;
  courseCode: string;
  courseId: number | null;
  socratic: boolean;
  onOpenSession: (id: string) => void;
  onOpenArtifact: (type: ArtifactType) => void;
  onOpenAssignment: (id: string) => void;
}) {
  const [askValue, setAskValue] = useState("");
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  const threadRef = useRef<HTMLDivElement>(null);
  const nextAssignment = course.assignments[0];
  const lastTurn = turns[turns.length - 1];
  const busy = lastTurn?.status === "loading" || lastTurn?.status === "streaming";
  const disabled = busy || courseId == null;

  async function send() {
    const question = askValue.trim();
    if (!question || disabled || courseId == null) return;
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
          {turns.length === 0 && (
            <div className="qa-empty">
              {courseId == null
                ? "Real Q&A isn't wired up for this course yet in this build."
                : "Ask a question about this course to get started."}
            </div>
          )}
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
            disabled={disabled}
            onChange={(e) => setAskValue(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && send()}
          />
          <button className="ask-send" onClick={send} disabled={disabled}>
            Ask
          </button>
        </div>
      </div>

      <div className="home-right">
        <div className="home-block">
          <div className="section-label">Next assignment</div>
          <button className="assign-card" onClick={() => onOpenAssignment(nextAssignment.id)}>
            <span className="main">
              <div className="ttl">{nextAssignment.title}</div>
              <div className="crs">
                {courseCode} · {nextAssignment.status}
              </div>
            </span>
            <span className="pill pill-ochre">Due {nextAssignment.due}</span>
            <span className="go">›</span>
          </button>
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
          <div className="session-list">
            {course.sessions.map((s) => (
              <button className="session-card" key={s.id} onClick={() => onOpenSession(s.id)}>
                <span className="num mono">{s.num}</span>
                <span className="meta">
                  <div className="ttl">{s.title}</div>
                  <div className="dt">
                    {s.date} · {s.duration}
                  </div>
                </span>
                <span className="go">›</span>
              </button>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
