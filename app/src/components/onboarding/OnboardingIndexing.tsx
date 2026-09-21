import { useEffect, useState } from "react";
import type { AvailableCourse } from "../../types";
import { syncCourse, type SyncEvent } from "../../sidecar";

interface CourseProgress {
  items: { name: string; failed: boolean }[];
  error: string | null;
  done: boolean;
}

export default function OnboardingIndexing({
  courses,
  onNext,
}: {
  courses: AvailableCourse[];
  onNext: () => void;
}) {
  const [progress, setProgress] = useState<CourseProgress[]>(courses.map(() => ({ items: [], error: null, done: false })));
  const allDone = progress.every((p) => p.done);

  useEffect(() => {
    let cancelled = false;

    async function syncAll() {
      // Sequential, not parallel — keeps each course's manifest.db usage
      // straightforward and avoids hammering Canvas with concurrent
      // requests across courses at once.
      for (let i = 0; i < courses.length; i++) {
        if (cancelled) return;
        const courseIndex = i;
        try {
          await syncCourse(courses[courseIndex].id, (event: SyncEvent) => {
            if (cancelled) return;
            setProgress((prev) =>
              prev.map((p, j) => {
                if (j !== courseIndex) return p;
                if (event.error) return { ...p, error: event.error, done: true };
                if (event.done) return { ...p, done: true };
                if (event.item) return { ...p, items: [...p.items, { name: event.item, failed: event.status === "failed" }] };
                return p;
              })
            );
          });
        } catch (err) {
          if (cancelled) return;
          const message = err instanceof Error ? err.message : "Sync failed";
          setProgress((prev) => prev.map((p, j) => (j === courseIndex ? { ...p, error: message, done: true } : p)));
        }
      }
    }

    syncAll();
    return () => {
      cancelled = true;
    };
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
          {courses.map((course, ci) => {
            const p = progress[ci];
            return (
              <div className="index-course" key={course.id}>
                <div className="icname">
                  {course.code} · {course.name}
                </div>
                {p.error && <div className="qa-a-error">{p.error}</div>}
                {!p.error && p.items.length === 0 && !p.done && <div className="qa-empty">Starting…</div>}
                {!p.error &&
                  p.items.map((item, ii) => (
                    <div className={"index-row" + (item.failed ? "" : " done")} key={ii}>
                      <span className="stat">{item.failed ? "!" : "✓"}</span>
                      <span>{item.name}</span>
                    </div>
                  ))}
              </div>
            );
          })}
        </div>
        <button className="btn-primary" disabled={!allDone} onClick={onNext}>
          Continue to SSB →
        </button>
      </div>
    </div>
  );
}
