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
  title = "Indexing your courses",
  subtitle = "This runs once — after this, everything stays local.",
  showSteps = true,
  continueLabel = "Continue to SSB →",
}: {
  courses: AvailableCourse[];
  onNext: () => void;
  title?: string;
  subtitle?: string;
  showSteps?: boolean;
  continueLabel?: string;
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
                // `done` first, not `error`: a per-item failure event also
                // carries an `error` field ({item, status: "failed", error})
                // but no `done`, so checking `error` first would hide the
                // whole course's progress behind one bad file and unlock
                // Continue while the stream is still running. Only a
                // terminal event's `error` means the course itself failed.
                if (event.done) {
                  return event.error ? { ...p, error: event.error, done: true } : { ...p, done: true };
                }
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
        // Defense in depth: the backend guarantees a terminal event, but if
        // a stream is ever truncated without one, this course's row would
        // stay non-done forever and Continue would never unlock. Once the
        // request has settled there's nothing more coming either way, so
        // mark it done — without clobbering an error already recorded.
        if (cancelled) return;
        setProgress((prev) => prev.map((p, j) => (j === courseIndex ? { ...p, done: true } : p)));
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
        {showSteps && (
          <div className="onboard-steps">
            <span className="onboard-dot done"></span>
            <span className="onboard-dot done"></span>
            <span className="onboard-dot active"></span>
          </div>
        )}
        <div>
          <h2 className="onboard-title">{title}</h2>
          <p className="onboard-sub">{subtitle}</p>
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
          {continueLabel}
        </button>
      </div>
    </div>
  );
}
