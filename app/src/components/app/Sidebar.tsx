import type { AvailableCourse } from "../../types";

export default function Sidebar({
  courses,
  activeCourseId,
  onCourseChange,
  onNewSession,
}: {
  courses: AvailableCourse[];
  activeCourseId: number;
  onCourseChange: (id: number) => void;
  onNewSession: () => void;
}) {
  return (
    <aside className="sidebar">
      <div className="brand">
        <span className="mark">SSB</span>
      </div>

      <div>
        <div className="nav-label">Courses</div>
        <div className="nav-group">
          {courses.map((c) => (
            <button
              key={c.id}
              className={"course-btn" + (c.id === activeCourseId ? " active" : "")}
              onClick={() => onCourseChange(c.id)}
            >
              <span className="dot"></span>
              {c.code}
            </button>
          ))}
        </div>
      </div>

      <div>
        <div className="nav-label-row">
          <span className="nav-label">Sessions</span>
          <button className="icon-btn nav-add" title="Record a new session" aria-label="Record a new session" onClick={onNewSession}>
            +
          </button>
        </div>
        <div className="nav-group">
          <div className="qa-empty">Past sessions aren't listed yet — recordings are still saved and indexed.</div>
        </div>
      </div>

      <div className="sidebar-foot">
        <div className="avatar">AJ</div>
        <div className="who">
          <div className="who-name">Arthur J.</div>
        </div>
        <button className="icon-btn" title="Settings" aria-label="Settings">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="12" cy="12" r="3"></circle>
            <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"></path>
          </svg>
        </button>
      </div>
    </aside>
  );
}
