import { useEffect, useState } from "react";
import type { AvailableCourse } from "../../types";
import { listCourses, writeConfig } from "../../sidecar";
import LogoMark from "../LogoMark";

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

  async function handleImport() {
    // Awaited, not best-effort: the next step (OnboardingIndexing) fires
    // POST /courses/{id}/sync immediately on mount, and main.py gates that
    // endpoint on _course_selected(), which reads exactly the config this
    // write produces. Advancing before the write lands means every course
    // 404s and nothing gets indexed — so a failure here stops onboarding
    // with a visible error instead of silently continuing.
    const selectedIds = courses.filter((c) => c.checked).map((c) => c.id);
    try {
      await writeConfig({ selected_courses: selectedIds, onboarding_complete: true });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't save your course selection");
      return;
    }
    onNext();
  }

  return (
    <div className="onboard">
      <div className="onboard-card">
        <button className="back-mini" onClick={onBack}>
          ‹ Back
        </button>
        <div className="onboard-icon">
          <LogoMark size={26} />
        </div>
        <div className="onboard-steps">
          <span className="onboard-dot done"></span>
          <span className="onboard-dot active"></span>
          <span className="onboard-dot"></span>
        </div>
        <div>
          <h2 className="onboard-title">Select your courses</h2>
          <p className="onboard-sub">Found on your Canvas — pick which ones Second Mind should index.</p>
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
