import { useRef, useState } from "react";
import type { AvailableCourse } from "../../types";
import type { ConversationSummary, SessionSummary } from "../../sidecar";
import { useDismissOnOutside } from "../../hooks/useDismissOnOutside";
import LogoMark from "../LogoMark";

function canvasHost(canvasBaseUrl: string): string {
  try {
    return new URL(canvasBaseUrl).host;
  } catch {
    return "Canvas";
  }
}

export default function Sidebar({
  courses,
  activeCourseId,
  onCourseChange,
  conversations,
  activeConversationId,
  onNewChat,
  onOpenConversation,
  onDeleteConversation,
  sessions,
  activeSessionId,
  onOpenSession,
  onNewSession,
  canvasBaseUrl,
  onManageCourses,
  onModelProvider,
}: {
  courses: AvailableCourse[];
  activeCourseId: number;
  onCourseChange: (id: number) => void;
  conversations: ConversationSummary[];
  activeConversationId: string | null;
  onNewChat: () => void;
  onOpenConversation: (id: string) => void;
  onDeleteConversation: (id: string) => Promise<void>;
  sessions: SessionSummary[];
  activeSessionId: string | null;
  onOpenSession: (id: string) => void;
  onNewSession: () => void;
  canvasBaseUrl: string;
  onManageCourses: () => void;
  onModelProvider: () => void;
}) {
  const [settingsOpen, setSettingsOpen] = useState(false);
  const settingsRef = useRef<HTMLDivElement>(null);
  useDismissOnOutside(settingsRef, settingsOpen, () => setSettingsOpen(false));

  // Recorded sessions stay folded until asked for, or while one is open.
  const [sessionsOpen, setSessionsOpen] = useState(false);
  const showSessions = sessionsOpen || activeSessionId !== null;
  const [confirmingDelete, setConfirmingDelete] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [deleteFailed, setDeleteFailed] = useState(false);

  function askDelete(id: string | null) {
    setDeleteFailed(false);
    setConfirmingDelete(id);
  }

  async function confirmDelete(id: string) {
    setDeleting(true);
    setDeleteFailed(false);
    try {
      await onDeleteConversation(id);
      setConfirmingDelete(null);
    } catch {
      setDeleteFailed(true);
    } finally {
      setDeleting(false);
    }
  }

  return (
    <aside className="sidebar" aria-label="Courses and chats">
      <div className="brand">
        <LogoMark size={16} className="brand-logo" />
        <span className="mark">Second Mind</span>
      </div>

      <button className="new-chat" type="button" onClick={onNewChat}>
        <svg viewBox="0 0 24 24" aria-hidden="true">
          <path d="M12 5v14M5 12h14" />
        </svg>
        New chat
      </button>

      <nav>
        <div className="nav-label">Courses</div>
        <div className="nav-group">
          {courses.map((c) => {
            const active = c.id === activeCourseId;
            return (
              <div className="course-group" key={c.id}>
                <button
                  className="course-btn"
                  type="button"
                  aria-current={active ? "true" : undefined}
                  title={c.name}
                  onClick={() => onCourseChange(c.id)}
                >
                  <span className="code">{c.code}</span>
                  <span className="cn">{c.name}</span>
                </button>
                {active && (
                  <div className="course-sub">
                    {conversations.length === 0 && <div className="side-empty">No saved chats yet.</div>}
                    {conversations.map((conv) =>
                      confirmingDelete === conv.conversation_id ? (
                        <div className="side-confirm" key={conv.conversation_id}>
                          <span>{deleteFailed ? "Couldn't delete. Try again?" : "Delete this chat?"}</span>
                          <button
                            type="button"
                            className="btn-danger"
                            disabled={deleting}
                            onClick={() => void confirmDelete(conv.conversation_id)}
                          >
                            Delete
                          </button>
                          <button
                            type="button"
                            className="icon-btn"
                            disabled={deleting}
                            onClick={() => askDelete(null)}
                          >
                            Cancel
                          </button>
                        </div>
                      ) : (
                        <div className="side-row" key={conv.conversation_id}>
                          <button
                            type="button"
                            className="side-link"
                            aria-current={conv.conversation_id === activeConversationId ? "true" : undefined}
                            title={conv.title}
                            onClick={() => onOpenConversation(conv.conversation_id)}
                          >
                            {conv.title}
                          </button>
                          <button
                            type="button"
                            className="side-del"
                            aria-label={`Delete chat: ${conv.title}`}
                            title="Delete chat"
                            onClick={() => askDelete(conv.conversation_id)}
                          >
                            <svg viewBox="0 0 24 24" aria-hidden="true">
                              <path d="M3 6h18M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                            </svg>
                          </button>
                        </div>
                      )
                    )}

                    <button
                      type="button"
                      className="side-toggle"
                      aria-expanded={showSessions}
                      onClick={() => setSessionsOpen(!showSessions)}
                    >
                      <svg viewBox="0 0 24 24" aria-hidden="true">
                        <path d="m9 6 6 6-6 6" />
                      </svg>
                      Recorded sessions
                      <span className="n">{sessions.length}</span>
                    </button>
                    {showSessions && (
                      <>
                        {sessions.map((s) => (
                          <div className="side-row" key={s.session_id}>
                            <button
                              type="button"
                              className="side-link"
                              aria-current={s.session_id === activeSessionId ? "true" : undefined}
                              title={s.title}
                              onClick={() => onOpenSession(s.session_id)}
                            >
                              {s.title}
                            </button>
                            {(s.status === "recording" || s.status === "processing") && (
                              <span className="session-status-dot" title="Processing…"></span>
                            )}
                            {s.status === "error" && (
                              <span className="side-warn" title="Couldn't be processed">
                                !
                              </span>
                            )}
                          </div>
                        ))}
                        <button type="button" className="side-add" onClick={onNewSession}>
                          <svg viewBox="0 0 24 24" aria-hidden="true">
                            <path d="M12 5v14M5 12h14" />
                          </svg>
                          Record a session
                        </button>
                      </>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </nav>

      <div className="sidebar-foot">
        <span className="canvas-status" title={canvasBaseUrl}>
          {canvasHost(canvasBaseUrl)}
        </span>
        <div className="settings-anchor" ref={settingsRef}>
          <button
            className="icon-btn"
            type="button"
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
              <button
                className="settings-menu-item"
                role="menuitem"
                onClick={() => {
                  setSettingsOpen(false);
                  onModelProvider();
                }}
              >
                Model provider
              </button>
            </div>
          )}
        </div>
      </div>
    </aside>
  );
}
