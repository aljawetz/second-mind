import { useRef, useState } from "react";
import type { ArtifactType, Course } from "../../types";
import { ARTIFACT_TYPES } from "../../data";

export default function HomeView({
  course,
  courseCode,
  onOpenSession,
  onOpenArtifact,
  onOpenAssignment,
}: {
  course: Course;
  courseCode: string;
  onOpenSession: (id: string) => void;
  onOpenArtifact: (type: ArtifactType) => void;
  onOpenAssignment: (id: string) => void;
}) {
  const [askValue, setAskValue] = useState("");
  const threadRef = useRef<HTMLDivElement>(null);
  const nextAssignment = course.assignments[0];

  function send() {
    if (askValue.trim()) setAskValue("");
    threadRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  return (
    <section id="view-home">
      <div className="chat-panel">
        <div className="chat-head">Ask about this course</div>
        <div className="qa-thread" ref={threadRef}>
          <div className="qa-q">{course.qa.q}</div>
          <div className="qa-a">
            {course.qa.a.map((p, i) => (
              <p key={i}>{p}</p>
            ))}
            <div className="qa-sources">
              <span>Sources</span>
              {course.qa.sources.map((s) => (
                <span className="cite" key={s}>
                  {s}
                </span>
              ))}
            </div>
          </div>
        </div>
        <div className="ask-bar">
          <input
            type="text"
            placeholder="Ask about this course…"
            value={askValue}
            onChange={(e) => setAskValue(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && send()}
          />
          <button className="ask-send" onClick={send}>
            Ask
          </button>
        </div>
      </div>

      <div className="home-right">
        <div className="home-block">
          <div className="section-label">Next assignment</div>
          <button className="assign-card" onClick={() => onOpenAssignment(nextAssignment.id)}>
            <span className="main">
              <div className="ttl">{nextAssignment.title}</div>
              <div className="crs">
                {courseCode} · {nextAssignment.status}
              </div>
            </span>
            <span className="pill pill-ochre">Due {nextAssignment.due}</span>
            <span className="go">›</span>
          </button>
        </div>

        <div className="home-block">
          <div className="section-label">Study artifacts</div>
          <div className="artifact-row">
            {ARTIFACT_TYPES.map((t) => (
              <button className="artifact-btn" key={t.key} onClick={() => onOpenArtifact(t.key)}>
                <span className="lbl">{t.lbl}</span>
                <span className="sub">{t.sub}</span>
              </button>
            ))}
          </div>
        </div>

        <div className="home-block">
          <div className="section-label">Recent sessions</div>
          <div className="session-list">
            {course.sessions.map((s) => (
              <button className="session-card" key={s.id} onClick={() => onOpenSession(s.id)}>
                <span className="num mono">{s.num}</span>
                <span className="meta">
                  <div className="ttl">{s.title}</div>
                  <div className="dt">
                    {s.date} · {s.duration}
                  </div>
                </span>
                <span className="go">›</span>
              </button>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
