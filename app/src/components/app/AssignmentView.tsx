import { useState } from "react";
import type { Course } from "../../types";

export default function AssignmentView({
  course,
  assignmentId,
  onBack,
}: {
  course: Course;
  assignmentId: string;
  onBack: () => void;
}) {
  const [explainOpen, setExplainOpen] = useState(false);
  const a = course.assignments.find((x) => x.id === assignmentId)!;

  return (
    <section id="view-assignment">
      <button className="back-link" onClick={onBack}>
        ‹ Course home
      </button>
      <div className="assign-head">
        <h2>{a.title}</h2>
      </div>
      <div className="assign-pills">
        <span className="pill pill-ochre">Due {a.due}</span>
        <span className="pill pill-neutral">{a.weight}</span>
        <span className="pill pill-neutral">{a.status}</span>
      </div>
      <div className="panel">
        <h3>Prompt</h3>
        <div className="assign-prompt">{a.prompt}</div>
      </div>
      <button className="explain-btn" onClick={() => setExplainOpen((o) => !o)}>
        {explainOpen ? "✦ Hide explanation" : "✦ Explain this assignment"}
      </button>
      {explainOpen && (
        <div className="panel explain-panel">
          <div className="explain-flag">
            <span className="pill">◆ grounded explanation</span>
            <span className="cav">Explains the prompt & points to source material — won't draft your answer.</span>
          </div>
          <div>
            <h3>What's being asked</h3>
            <ul className="explain-list">
              {a.explain.breakdown.map((pt, i) => (
                <li key={i}>{pt}</li>
              ))}
            </ul>
          </div>
          <div>
            <h3>Where to start</h3>
            <div className="explain-tips">
              {a.explain.tips.map((t, i) => (
                <div className="explain-tip" key={i}>
                  <span className="cite">{t.src}</span>
                  <span>{t.text}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
