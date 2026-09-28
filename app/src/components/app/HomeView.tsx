import { useRef, useState } from "react";
import type { ArtifactType } from "../../types";
import { ARTIFACT_TYPES } from "../../data";
import { askQuestion, type Citation, type MemoryUsed } from "../../sidecar";
import { splitAssignments, statusPill } from "../../assignmentStatus";
import type { CanvasAssignment } from "../../sidecar";
import { openCitation } from "../../citations";

// Must match chat.py's GENERAL_KNOWLEDGE_LABEL: the model starts the part of
// its answer that isn't from the course with this exact line.
const GENERAL_KNOWLEDGE_LABEL = "General knowledge (not from your course materials):";

// Shows the general-knowledge part as its own marked block, so the student
// can tell it apart from the cited course answer without relying on the
// model's wording alone.
function AnswerText({ answer }: { answer: string }) {
  const at = answer.indexOf(GENERAL_KNOWLEDGE_LABEL);
  const course = (at === -1 ? answer : answer.slice(0, at)).trim();
  const general = at === -1 ? null : answer.slice(at + GENERAL_KNOWLEDGE_LABEL.length).trim();
  return (
    <>
      {course && <p className="qa-text">{course}</p>}
      {general !== null && (
        <div className="qa-general">
          <div className="qa-general-head">General knowledge · not from your course materials</div>
          {general && <p className="qa-text">{general}</p>}
        </div>
      )}
    </>
  );
}

interface ChatTurn {
  question: string;
  answer: string;
  citations: Citation[];
  grounded: boolean;
  memoriesUsed: MemoryUsed[];
  status: "loading" | "streaming" | "done" | "error";
  error?: string;
}

export default function HomeView({
  courseId,
  courseName,
  canvasBaseUrl,
  assignments,
  assignmentsError,
  onOpenArtifact,
  onOpenAssignment,
  onOpenSession,
}: {
  courseId: number;
  courseName: string;
  canvasBaseUrl: string;
  assignments: CanvasAssignment[];
  assignmentsError: string | null;
  onOpenArtifact: (type: ArtifactType) => void;
  onOpenAssignment: (id: number) => void;
  onOpenSession: (sessionId: string) => void;
}) {
  const [askValue, setAskValue] = useState("");
  const [turns, setTurns] = useState<ChatTurn[]>([]);
  // The backend's id for this chat, from its first answer: sent with every
  // later question so the chat continues where it is saved. AppShell mounts
  // a fresh HomeView per course, which starts a new chat.
  const [conversationId, setConversationId] = useState<string | null>(null);
  const threadRef = useRef<HTMLDivElement>(null);
  const { upcoming, past } = splitAssignments(assignments);
  const lastTurn = turns[turns.length - 1];
  const busy = lastTurn?.status === "loading" || lastTurn?.status === "streaming";

  // Past assignments start collapsed — upcoming work is what needs
  // attention, past/completed is there to check but not worth the space.
  const [openGroups, setOpenGroups] = useState({ upcoming: true, past: false });
  function toggleGroup(key: "upcoming" | "past") {
    setOpenGroups((g) => ({ ...g, [key]: !g[key] }));
  }

  function renderAssignList(list: CanvasAssignment[]) {
    return (
      <div className="assign-list">
        {list.map((a) => {
          const pill = statusPill(a);
          return (
            <button className="assign-card" key={a.id} onClick={() => onOpenAssignment(a.id)}>
              <span className="main">
                <div className="ttl">{a.name}</div>
                <div className="crs">{courseName}</div>
              </span>
              <span className={`pill ${pill.cls}`}>{pill.text}</span>
              <span className="go">›</span>
            </button>
          );
        })}
      </div>
    );
  }

  async function send() {
    const question = askValue.trim();
    if (!question || busy) return;
    setAskValue("");
    const turnIndex = turns.length;
    // Only finished turns: an errored or half-streamed answer would give the
    // model a wrong picture of what it already said.
    const history = turns.filter((t) => t.status === "done").map((t) => ({ question: t.question, answer: t.answer }));
    setTurns((prev) => [
      ...prev,
      { question, answer: "", citations: [], grounded: false, memoriesUsed: [], status: "loading" },
    ]);
    threadRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });

    const update = (patch: Partial<ChatTurn>) =>
      setTurns((prev) => prev.map((t, i) => (i === turnIndex ? { ...t, ...patch } : t)));
    const conversationIdAtSend = conversationId;

    try {
      await askQuestion(courseId, courseName, question, history, conversationId, (event) => {
        if (event.conversation_id) {
          setConversationId(event.conversation_id);
        }
        if (event.delta) {
          setTurns((prev) =>
            prev.map((t, i) => (i === turnIndex ? { ...t, answer: t.answer + event.delta, status: "streaming" } : t))
          );
        }
        if (event.citations !== undefined) {
          update({ citations: event.citations, grounded: !!event.grounded, memoriesUsed: event.memories_used ?? [] });
        }
        if (event.error) {
          update({ status: "error", error: event.error });
          // A new chat's id is sent before the turn is saved; drop it so the
          // next question starts fresh instead of 404ing forever.
          if (conversationIdAtSend === null) {
            setConversationId(null);
          }
        }
        if (event.done) {
          setTurns((prev) => prev.map((t, i) => (i === turnIndex && t.status !== "error" ? { ...t, status: "done" } : t)));
        }
      });
    } catch (err) {
      update({ status: "error", error: err instanceof Error ? err.message : "Something went wrong" });
      if (conversationIdAtSend === null) {
        setConversationId(null);
      }
    }
  }

  return (
    <section id="view-home">
      <div className="home-left">
        <div className="home-block">
          <div className="section-label">Study artifacts</div>
          <div className="artifact-row">
            {ARTIFACT_TYPES.map((t) => (
              <button className={`artifact-btn artifact-${t.key}`} key={t.key} onClick={() => onOpenArtifact(t.key)}>
                <span className="lbl">{t.lbl}</span>
                <span className="sub">{t.sub}</span>
              </button>
            ))}
          </div>
        </div>

        <div className="chat-panel">
          <div className="chat-head">Ask about this course</div>
          <div className="qa-thread" ref={threadRef}>
            {turns.length === 0 && <div className="qa-empty">Ask a question about this course to get started.</div>}
            {turns.map((turn, i) => (
              <div key={i}>
                <div className="qa-q">{turn.question}</div>
                {turn.status === "error" ? (
                  <div className="qa-a qa-a-error">{turn.error}</div>
                ) : (
                  <div className="qa-a">
                    {turn.status === "loading" ? (
                      <p className="qa-thinking">Searching your course…</p>
                    ) : (
                      <>
                        <AnswerText answer={turn.answer} />
                        {turn.grounded && turn.citations.length > 0 && (
                          <div className="qa-sources">
                            <span>Sources</span>
                            {turn.citations.map((c, ci) => (
                              <button
                                className="cite cite-link"
                                key={ci}
                                onClick={() => openCitation(canvasBaseUrl, courseId, c, onOpenSession)}
                              >
                                [{ci + 1}] {c.label}
                              </button>
                            ))}
                          </div>
                        )}
                        {turn.memoriesUsed.length > 0 && (
                          <div className="qa-memories">
                            <span>From what you told me before</span>
                            {turn.memoriesUsed.map((m) => (
                              <span className="memory-chip" key={m.id}>
                                {m.text}
                              </span>
                            ))}
                          </div>
                        )}
                      </>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
          <div className="ask-bar">
            <input
              type="text"
              placeholder="Ask about this course…"
              value={askValue}
              disabled={busy}
              onChange={(e) => setAskValue(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && send()}
            />
            <button className="ask-send" onClick={send} disabled={busy}>
              Ask
            </button>
          </div>
        </div>
      </div>

      <div className="home-right">
        <div className="home-block">
          <div className="section-label">Assignments</div>
          {assignmentsError && <div className="qa-a-error">{assignmentsError}</div>}
          {!assignmentsError && assignments.length === 0 && <div className="qa-empty">No assignments found.</div>}
          {!assignmentsError && assignments.length > 0 && (
            <div className="assign-scroll">
              <div className="assign-group">
                <button className="assign-group-head" onClick={() => toggleGroup("upcoming")}>
                  <span className="chevron">{openGroups.upcoming ? "▾" : "▸"}</span>
                  Upcoming
                  <span className="count">{upcoming.length}</span>
                </button>
                {openGroups.upcoming &&
                  (upcoming.length > 0 ? renderAssignList(upcoming) : <div className="qa-empty">Nothing upcoming.</div>)}
              </div>

              {past.length > 0 && (
                <div className="assign-group">
                  <button className="assign-group-head" onClick={() => toggleGroup("past")}>
                    <span className="chevron">{openGroups.past ? "▾" : "▸"}</span>
                    Past &amp; completed
                    <span className="count">{past.length}</span>
                  </button>
                  {openGroups.past && renderAssignList(past)}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
