import { useEffect, useState } from "react";
import type { AvailableCourse } from "../../types";
import { deleteCourse, listCourses, unselectCourse, writeConfig, type CanvasCourse } from "../../sidecar";

export default function ManageCoursesView({
  courses,
  onBack,
  onCourseRemoved,
  onCourseAdded,
}: {
  courses: AvailableCourse[];
  onBack: () => void;
  onCourseRemoved: (courseId: number) => void;
  onCourseAdded: (course: AvailableCourse) => void;
}) {
  const [confirmingDeleteId, setConfirmingDeleteId] = useState<number | null>(null);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [error, setError] = useState("");

  const [catalog, setCatalog] = useState<CanvasCourse[] | null>(null);
  const [catalogError, setCatalogError] = useState("");
  const [addingId, setAddingId] = useState<number | null>(null);

  const isLastCourse = courses.length <= 1;

  // The full Canvas course catalog isn't otherwise kept around post-
  // onboarding (App.tsx only threads the already-selected subset down to
  // AppShell), so this is fetched fresh here rather than plumbed through
  // every intermediate component just for this one screen.
  useEffect(() => {
    listCourses()
      .then(setCatalog)
      .catch((err) => setCatalogError(err instanceof Error ? err.message : "Couldn't load your Canvas courses"));
  }, []);

  const selectedIds = new Set(courses.map((c) => c.id));
  const addable = (catalog ?? []).filter((c) => !selectedIds.has(c.id));

  async function handleArchive(courseId: number) {
    setConfirmingDeleteId(null);
    setBusyId(courseId);
    setError("");
    try {
      await unselectCourse(courseId);
      onCourseRemoved(courseId);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't archive this course");
    } finally {
      setBusyId(null);
    }
  }

  async function handleDelete(course: AvailableCourse) {
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
    }
  }

  // POST /config merges at the top level (main.py: {...read_config(), ...data}),
  // not per-array-element — the full desired selected_courses list has to be
  // sent, not just the id being added.
  async function handleAdd(course: CanvasCourse) {
    setAddingId(course.id);
    setError("");
    try {
      await writeConfig({ selected_courses: [...courses.map((c) => c.id), course.id] });
      onCourseAdded({ id: course.id, code: course.code ?? String(course.id), name: course.name, checked: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't add this course");
    } finally {
      setAddingId(null);
    }
  }

  return (
    <section id="view-new-session">
      <button className="back-link" onClick={onBack}>
        ‹ Course home
      </button>
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
                <button
                  className="btn-danger"
                  disabled={busyId === c.id}
                  onClick={() => void handleDelete(c)}
                >
                  Confirm delete
                </button>
                <button
                  className="icon-btn"
                  disabled={busyId === c.id}
                  onClick={() => setConfirmingDeleteId(null)}
                >
                  Cancel
                </button>
              </span>
            ) : (
              <span className="manage-actions">
                <button
                  className="icon-btn"
                  title="Archive — keeps your indexed data, just hides it from the sidebar"
                  disabled={isLastCourse || busyId === c.id}
                  onClick={() => handleArchive(c.id)}
                >
                  Archive
                </button>
                <button
                  className="icon-btn icon-btn-danger"
                  title="Delete — permanently removes this course's data"
                  disabled={isLastCourse || busyId === c.id}
                  onClick={() => setConfirmingDeleteId(c.id)}
                >
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M3 6h18"></path>
                    <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
                    <line x1="10" y1="11" x2="10" y2="17"></line>
                    <line x1="14" y1="11" x2="14" y2="17"></line>
                  </svg>
                  Delete
                </button>
              </span>
            )}
          </div>
        ))}
      </div>

      <div className="home-block">
        <div className="section-label">Add a course</div>
        {catalogError && <p className="qa-a-error">{catalogError}</p>}
        {!catalogError && catalog === null && <p className="qa-thinking">Loading your Canvas courses…</p>}
        {!catalogError && catalog !== null && addable.length === 0 && (
          <div className="qa-empty">Every course from Canvas is already added.</div>
        )}
        {addable.length > 0 && (
          <div className="course-pick">
            {addable.map((c) => (
              <div className="course-row" key={c.id}>
                <span className="cmeta">
                  <div className="ccode">{c.code ?? c.id}</div>
                  <div className="cname">{c.name}</div>
                </span>
                <span className="manage-actions">
                  <button className="icon-btn" disabled={addingId === c.id} onClick={() => handleAdd(c)}>
                    + Add
                  </button>
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </section>
  );
}
