import { useState } from "react";
import { explainAssignment, type AssignmentExplanation, type CanvasAssignment } from "../../sidecar";

type ExplainState =
  | { status: "closed" }
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "done"; data: AssignmentExplanation };

function formatDue(dueAt: string | null): string {
  if (!dueAt) return "No due date";
  return new Date(dueAt).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export default function AssignmentView({
  courseId,
  assignment,
  onBack,
}: {
  courseId: number;
  assignment: CanvasAssignment;
  onBack: () => void;
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
      <div className="assign-pills">
        <span className="pill pill-ochre">Due {formatDue(assignment.due_at)}</span>
        {assignment.points_possible != null && (
          <span className="pill pill-neutral">{assignment.points_possible} pts</span>
        )}
      </div>
      <div className="panel">
        <h3>Prompt</h3>
        <div className="assign-prompt">{assignment.description || "No description provided."}</div>
      </div>
      <button className="explain-btn" onClick={toggleExplain}>
        {open ? "✦ Hide explanation" : "✦ Explain this assignment"}
      </button>
      {open && (
        <div className="panel explain-panel">
          <div className="explain-flag">
            <span className="pill">◆ grounded explanation</span>
            <span className="cav">Explains the prompt & points to source material — won't draft your answer.</span>
          </div>
          {explain.status === "loading" && <p className="qa-thinking">Thinking…</p>}
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
                <div className="explain-tips">
                  {explain.data.pointers.length === 0 && (
                    <div className="qa-empty">Nothing in your indexed course material came up as relevant.</div>
                  )}
                  {explain.data.pointers.map((p, i) => (
                    <div className="explain-tip" key={i}>
                      <span className="cite">{p.label}</span>
                    </div>
                  ))}
                </div>
              </div>
            </>
          )}
        </div>
      )}
    </section>
  );
}
