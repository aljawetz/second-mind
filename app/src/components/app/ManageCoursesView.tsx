import { useState } from "react";
import type { AvailableCourse } from "../../types";
import { deleteCourse, unselectCourse } from "../../sidecar";

export default function ManageCoursesView({
  courses,
  onBack,
  onCourseRemoved,
}: {
  courses: AvailableCourse[];
  onBack: () => void;
  onCourseRemoved: (courseId: number) => void;
}) {
  const [confirmingDeleteId, setConfirmingDeleteId] = useState<number | null>(null);
  const [confirmText, setConfirmText] = useState("");
  const [busyId, setBusyId] = useState<number | null>(null);
  const [error, setError] = useState("");

  const isLastCourse = courses.length <= 1;

  async function handleUnselect(courseId: number) {
    setBusyId(courseId);
    setError("");
    try {
      await unselectCourse(courseId);
      onCourseRemoved(courseId);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't remove this course");
    } finally {
      setBusyId(null);
    }
  }

  async function handleDelete(course: AvailableCourse) {
    if (confirmText.trim() !== course.code) return;
    setBusyId(course.id);
    setError("");
    try {
      await deleteCourse(course.id);
      onCourseRemoved(course.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't delete this course");
    } finally {
      setBusyId(null);
      setConfirmingDeleteId(null);
      setConfirmText("");
    }
  }

  return (
    <section id="view-new-session">
      <button className="back-link" onClick={onBack}>
        ‹ Course home
      </button>
      <div className="assign-head">
        <h2>Manage courses</h2>
      </div>
      {error && <p className="qa-a-error">{error}</p>}
      {isLastCourse && <p className="qa-empty">This is your only course — add another before removing it.</p>}
      <div className="course-pick">
        {courses.map((c) => (
          <div className="course-row" key={c.id}>
            <span className="cmeta">
              <div className="ccode">{c.code}</div>
              <div className="cname">{c.name}</div>
            </span>
            {confirmingDeleteId === c.id ? (
              <span className="manage-confirm">
                <input
                  type="text"
                  placeholder={`Type "${c.code}" to confirm`}
                  value={confirmText}
                  onChange={(e) => setConfirmText(e.target.value)}
                  autoFocus
                />
                <button
                  className="explain-btn"
                  disabled={confirmText.trim() !== c.code || busyId === c.id}
                  onClick={() => handleDelete(c)}
                >
                  Confirm delete
                </button>
                <button
                  className="icon-btn"
                  onClick={() => {
                    setConfirmingDeleteId(null);
                    setConfirmText("");
                  }}
                >
                  Cancel
                </button>
              </span>
            ) : (
              <span className="manage-actions">
                <button className="icon-btn" disabled={isLastCourse || busyId === c.id} onClick={() => handleUnselect(c.id)}>
                  Unselect
                </button>
                <button
                  className="icon-btn"
                  disabled={isLastCourse || busyId === c.id}
                  onClick={() => setConfirmingDeleteId(c.id)}
                >
                  🗑 Delete
                </button>
              </span>
            )}
          </div>
        ))}
      </div>
    </section>
  );
}
