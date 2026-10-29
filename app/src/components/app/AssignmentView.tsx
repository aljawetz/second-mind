import { useState } from "react";
import { explainAssignment, type AssignmentExplanation, type CanvasAssignment } from "../../sidecar";
import { openCitation } from "../../citations";
import { statusText } from "../../assignmentStatus";
import { SOURCE_KIND } from "./Answer";

type ExplainState =
  | { status: "closed" }
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "done"; data: AssignmentExplanation };

export default function AssignmentView({
  courseId,
  canvasBaseUrl,
  assignment,
  onBack,
  onOpenSession,
}: {
  courseId: number;
  canvasBaseUrl: string;
  assignment: CanvasAssignment;
  onBack: () => void;
  onOpenSession: (sessionId: string) => void;
}) {
  const [explain, setExplain] = useState<ExplainState>({ status: "closed" });

  async function toggleExplain() {
    if (explain.status !== "closed") {
      setExplain({ status: "closed" });
      return;
    }
    setExplain({ status: "loading" });
    try {
      const data = await explainAssignment(courseId, assignment.id);
      setExplain({ status: "done", data });
    } catch (err) {
      setExplain({ status: "error", message: err instanceof Error ? err.message : "Something went wrong" });
    }
  }

  const open = explain.status !== "closed";

  return (
    <section id="view-assignment">
      <button className="back-link" onClick={onBack}>
        ‹ Course home
      </button>
      <div className="assign-head">
        <h2>{assignment.name}</h2>
      </div>
      {(() => {
        const status = statusText(assignment);
        const dueLong = assignment.due_at
          ? new Date(assignment.due_at).toLocaleString(undefined, { weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })
          : null;
        return (
          <p className="assign-meta">
            <span className={status.tone}>{status.text}</span>
            {dueLong && <span>{dueLong}</span>}
          </p>
        );
      })()}
      <div className="panel">
        <h3>Prompt</h3>
        <div className="assign-prompt">{assignment.description || "No description provided."}</div>
      </div>
      <button className="explain-btn" onClick={toggleExplain}>
        {open ? "Hide explanation" : "Explain this assignment"}
      </button>
      {open && (
        <div className="panel explain-panel">
          <div className="explain-flag">
            <h3>Grounded explanation</h3>
            <span className="cav">Explains the prompt and points to source material. It won't draft your answer.</span>
          </div>
          {explain.status === "loading" && <p className="qa-thinking">Reading the prompt and searching your course</p>}
          {explain.status === "error" && <p className="qa-a-error">{explain.message}</p>}
          {explain.status === "done" && (
            <>
              <div>
                <h3>What's being asked</h3>
                <ul className="explain-list">
                  {explain.data.breakdown.map((pt, i) => (
                    <li key={i}>{pt}</li>
                  ))}
                </ul>
              </div>
              <div>
                <h3>Where to start</h3>
                {explain.data.pointers.length === 0 && (
                  <div className="qa-empty">Nothing in your indexed course material came up as relevant.</div>
                )}
                {explain.data.pointers.length > 0 && (
                  <ol className="qa-notes" aria-label="Where to start">
                    {explain.data.pointers.map((p, i) => (
                      <li key={i}>
                        <button type="button" onClick={() => openCitation(canvasBaseUrl, courseId, p, onOpenSession)}>
                          <span className="n">{i + 1}</span>
                          <span className="src">{p.label}</span>
                          <span className="kind">{SOURCE_KIND[p.source_type] ?? "Source"}</span>
                        </button>
                      </li>
                    ))}
                  </ol>
                )}
              </div>
            </>
          )}
        </div>
      )}
    </section>
  );
}
