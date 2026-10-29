import { useState, type ReactNode } from "react";
import { countdownPercent, dueParts, splitAssignments, statusText } from "../../assignmentStatus";
import type { CanvasAssignment, Citation, SessionSummary } from "../../sidecar";
import { openCitation } from "../../citations";
import ChatPanel from "./ChatPanel";

const Chevron = () => (
  <svg className="chev" viewBox="0 0 24 24" aria-hidden="true">
    <path d="m9 6 6 6-6 6" />
  </svg>
);

// Starting points for an empty chat, from what the course actually has.
function suggestionsFor(upcoming: CanvasAssignment[], sessions: SessionSummary[]): string[] {
  const out: string[] = [];
  if (upcoming[0]) out.push(`What does ${upcoming[0].name} ask me to do?`);
  const lecture = sessions.find((s) => s.status === "done");
  if (lecture) out.push(`Summarize ${lecture.title}`);
  out.push("What topics has this course covered so far?");
  return out;
}

export default function HomeView({
  courseId,
  courseName,
  canvasBaseUrl,
  assignments,
  assignmentsError,
  sessions,
  conversationId,
  initialQuestion,
  onInitialQuestionSent,
  studyPanel,
  onConversationSaved,
  onOpenAssignment,
  onOpenSession,
}: {
  courseId: number;
  courseName: string;
  canvasBaseUrl: string;
  assignments: CanvasAssignment[];
  assignmentsError: string | null;
  sessions: SessionSummary[];
  conversationId: string | null;
  initialQuestion: string | null;
  onInitialQuestionSent: () => void;
  studyPanel: ReactNode;
  onConversationSaved: (conversationId: string) => void;
  onOpenAssignment: (id: number) => void;
  onOpenSession: (sessionId: string) => void;
}) {
  const { upcoming, past } = splitAssignments(assignments);
  // Upcoming work is what needs attention; past work is there to check.
  const [pastOpen, setPastOpen] = useState(false);

  // The first upcoming item due within a week gets the countdown bar.
  const countdownId = upcoming.find((a) => countdownPercent(a) !== null)?.id;

  function renderRows(list: CanvasAssignment[]) {
    return list.map((a) => {
      const status = statusText(a);
      const when = dueParts(a.due_at);
      const percent = a.id === countdownId ? countdownPercent(a) : null;
      return (
        <button className="assign-row" key={a.id} type="button" onClick={() => onOpenAssignment(a.id)}>
          <span className="when">
            <span className="day">{when.day}</span>
            <span className="dow">{when.dow}</span>
          </span>
          <span className="body">
            <span className="ttl">{a.name}</span>
            <span className={`status ${status.tone}`}>{status.text}</span>
            {percent !== null && (
              <span className="count" aria-hidden="true">
                <i style={{ width: `${percent}%` }}></i>
              </span>
            )}
          </span>
        </button>
      );
    });
  }

  return (
    <section id="view-home">
      <ChatPanel
        courseId={courseId}
        courseName={courseName}
        conversationId={conversationId}
        suggestions={suggestionsFor(upcoming, sessions)}
        initialQuestion={initialQuestion}
        onInitialQuestionSent={onInitialQuestionSent}
        onConversationSaved={onConversationSaved}
        onOpenCitation={(c: Citation) => void openCitation(canvasBaseUrl, courseId, c, onOpenSession)}
      />

      <div className="home-side">
        <section className="assign-panel" aria-label="Assignments">
          <div className="assign-top">
            <h2>Assignments</h2>
            {!assignmentsError && assignments.length > 0 && <span>{upcoming.length} upcoming</span>}
          </div>
          <div className="assign-body">
            {assignmentsError && <p className="qa-a-error">{assignmentsError}</p>}
            {!assignmentsError && assignments.length === 0 && <p className="qa-empty">No assignments found.</p>}
            {!assignmentsError && assignments.length > 0 && (
              <>
                {upcoming.length > 0 ? renderRows(upcoming) : <p className="qa-empty">Nothing upcoming.</p>}
                {past.length > 0 && (
                  <>
                    <button
                      className="assign-toggle"
                      type="button"
                      aria-expanded={pastOpen}
                      onClick={() => setPastOpen((o) => !o)}
                    >
                      <Chevron />
                      Past and completed
                      <span className="n">{past.length}</span>
                    </button>
                    {pastOpen && renderRows(past)}
                  </>
                )}
              </>
            )}
          </div>
        </section>
        {studyPanel}
      </div>
    </section>
  );
}
