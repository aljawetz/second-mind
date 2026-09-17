import { useEffect, useState } from "react";
import type { AvailableCourse } from "../../types";
import { listCourses, writeConfig } from "../../sidecar";

export default function OnboardingCourses({
  courses,
  onChange,
  onBack,
  onNext,
}: {
  courses: AvailableCourse[];
  onChange: (courses: AvailableCourse[]) => void;
  onBack: () => void;
  onNext: () => void;
}) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const selectedCount = courses.filter((c) => c.checked).length;

  useEffect(() => {
    if (courses.length > 0) return; // already loaded — e.g. navigated back then forward
    setLoading(true);
    setError("");
    listCourses()
      .then((fetched) =>
        onChange(
          fetched.map((c) => ({ id: c.id, code: c.code ?? String(c.id), name: c.name, checked: false }))
        )
      )
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function toggle(idx: number) {
    onChange(courses.map((c, i) => (i === idx ? { ...c, checked: !c.checked } : c)));
  }

  function handleImport() {
    // Persisted so a future launch can skip onboarding (App.tsx's
    // returning-user check) — best-effort: if this write fails, onboarding
    // just runs again next time, which is a safe fallback, not a blocker.
    const selectedIds = courses.filter((c) => c.checked).map((c) => c.id);
    writeConfig({ selected_courses: selectedIds, llm_provider: "openai", onboarding_complete: true }).catch(
      (e) => console.error("failed to persist course selection", e)
    );
    onNext();
  }

  return (
    <div className="onboard">
      <div className="onboard-card">
        <button className="back-mini" onClick={onBack}>
          ‹ Back
        </button>
        <div className="onboard-steps">
          <span className="onboard-dot done"></span>
          <span className="onboard-dot active"></span>
          <span className="onboard-dot"></span>
        </div>
        <div>
          <h2 className="onboard-title">Select your courses</h2>
          <p className="onboard-sub">Found on canvas.cmu.edu — pick which ones SSB should index.</p>
        </div>
        {loading && <p className="onboard-sub">Loading your courses…</p>}
        {error && <p className="field-error">{error}</p>}
        {!loading && !error && (
          <div className="course-pick">
            {courses.map((c, i) => (
              <label className="course-row" key={c.id}>
                <input type="checkbox" checked={c.checked} onChange={() => toggle(i)} />
                <span className="cmeta">
                  <div className="ccode">{c.code}</div>
                  <div className="cname">{c.name}</div>
                </span>
              </label>
            ))}
          </div>
        )}
        <div className="course-count">{selectedCount} selected</div>
        <button className="btn-primary" disabled={selectedCount === 0} onClick={handleImport}>
          Import selected courses →
        </button>
      </div>
    </div>
  );
}
