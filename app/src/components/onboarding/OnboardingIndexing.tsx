import { useEffect, useState } from "react";
import { DATA } from "../../data";

type RowStatus = "pending" | "busy" | "done";
const LABELS = ["Assignments", "Modules", "Slides & files"] as const;

export default function OnboardingIndexing({ onNext }: { onNext: () => void }) {
  const courseCodes = Object.keys(DATA);
  const [rows, setRows] = useState<RowStatus[]>(
    Array(courseCodes.length * LABELS.length).fill("pending")
  );
  const done = rows.every((r) => r === "done");

  useEffect(() => {
    const timers: ReturnType<typeof setTimeout>[] = [];
    rows.forEach((_, i) => {
      timers.push(
        setTimeout(() => {
          setRows((prev) => prev.map((r, j) => (j === i ? "busy" : r)));
        }, i * 260)
      );
      timers.push(
        setTimeout(() => {
          setRows((prev) => prev.map((r, j) => (j === i ? "done" : r)));
        }, i * 260 + 380)
      );
    });
    return () => timers.forEach(clearTimeout);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="onboard">
      <div className="onboard-card">
        <div className="onboard-steps">
          <span className="onboard-dot done"></span>
          <span className="onboard-dot done"></span>
          <span className="onboard-dot active"></span>
        </div>
        <div>
          <h2 className="onboard-title">Indexing your courses</h2>
          <p className="onboard-sub">This runs once — after this, everything stays local.</p>
        </div>
        <div className="index-list">
          {courseCodes.map((code, ci) => (
            <div className="index-course" key={code}>
              <div className="icname">{DATA[code].code}</div>
              {LABELS.map((label, li) => {
                const status = rows[ci * LABELS.length + li];
                return (
                  <div className={"index-row" + (status === "busy" ? " busy" : status === "done" ? " done" : "")} key={label}>
                    <span className="stat">{status === "done" ? "✓" : ""}</span>
                    <span>{label}</span>
                  </div>
                );
              })}
            </div>
          ))}
        </div>
        <button className="btn-primary" disabled={!done} onClick={onNext}>
          Continue to SSB →
        </button>
      </div>
    </div>
  );
}
