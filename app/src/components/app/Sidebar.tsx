import { useRef, useState } from "react";
import type { AvailableCourse } from "../../types";
import type { SessionSummary } from "../../sidecar";
import { useDismissOnOutside } from "../../hooks/useDismissOnOutside";
import LogoMark from "../LogoMark";

export default function Sidebar({
  courses,
  activeCourseId,
  onCourseChange,
  onNewSession,
  sessions,
  activeSessionId,
  onOpenSession,
  onManageCourses,
}: {
  courses: AvailableCourse[];
  activeCourseId: number;
  onCourseChange: (id: number) => void;
  onNewSession: () => void;
  sessions: SessionSummary[];
  activeSessionId: string | null;
  onOpenSession: (id: string) => void;
  onManageCourses: () => void;
}) {
  const [settingsOpen, setSettingsOpen] = useState(false);
  const settingsRef = useRef<HTMLDivElement>(null);

  useDismissOnOutside(settingsRef, settingsOpen, () => setSettingsOpen(false));

  return (
    <aside className="sidebar">
      <div className="brand">
        <LogoMark size={15} className="brand-logo" />
        <span className="mark">Second Mind</span>
      </div>

      <div>
        <div className="nav-label">Courses</div>
        <div className="nav-group">
          {courses.map((c) => {
            const active = c.id === activeCourseId;
            return (
              <div className="course-group" key={c.id}>
                <button
                  className={"course-btn" + (active ? " active" : "")}
                  onClick={() => onCourseChange(c.id)}
                >
                  <span className="dot"></span>
                  {c.code}
                  <span className="chevron">{active ? "▾" : "▸"}</span>
                </button>
                {active && (
                  <div className="session-group">
                    {sessions.length === 0 && <div className="qa-empty">No sessions yet.</div>}
                    {sessions.map((s) => (
                      <button
                        key={s.session_id}
                        className={"session-btn" + (s.session_id === activeSessionId ? " active" : "")}
                        onClick={() => onOpenSession(s.session_id)}
                      >
                        <span>{s.title}</span>
                        {(s.status === "recording" || s.status === "processing") && (
                          <span className="session-status-dot busy" title="Processing…"></span>
                        )}
                        {s.status === "error" && (
                          <span className="sdate" title="Couldn't be processed">
                            ⚠
                          </span>
                        )}
                      </button>
                    ))}
                    <button className="session-add" title="Record a new session" aria-label="Record a new session" onClick={onNewSession}>
                      <span className="plus">+</span> New session
                    </button>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>

      <div className="sidebar-foot">
        <div className="avatar">AJ</div>
        <div className="who">
          <div className="who-name">Arthur J.</div>
        </div>
        <div className="settings-anchor" ref={settingsRef}>
          <button
            className="icon-btn"
            title="Settings"
            aria-label="Settings"
            aria-expanded={settingsOpen}
            onClick={() => setSettingsOpen((o) => !o)}
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="12" cy="12" r="3"></circle>
              <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"></path>
            </svg>
          </button>
          {settingsOpen && (
            <div className="settings-menu" role="menu">
              <button
                className="settings-menu-item"
                role="menuitem"
                onClick={() => {
                  setSettingsOpen(false);
                  onManageCourses();
                }}
              >
                Manage courses
              </button>
            </div>
          )}
        </div>
      </div>
    </aside>
  );
}
