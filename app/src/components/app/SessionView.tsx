import type { Course } from "../../types";
import { WAVE } from "../../data";

export default function SessionView({
  course,
  sessionId,
  onBack,
}: {
  course: Course;
  sessionId: string;
  onBack: () => void;
}) {
  const meta = course.sessions.find((s) => s.id === sessionId)!;
  const detail = course.session[sessionId] ?? Object.values(course.session)[0];

  return (
    <section id="view-session">
      <button className="back-link" onClick={onBack}>
        ‹ Course home
      </button>
      <div className="session-head">
        <h2>
          Class {meta.num} — {meta.title}
        </h2>
        <span className="code mono">{meta.date}</span>
      </div>
      <div className="split">
        <div className="panel">
          <h3>Recording</h3>
          <div className="player">
            <div className="waveform">
              {WAVE.map((h, i) => (
                <i key={i} style={{ height: h }} className={i < 15 ? "played" : ""}></i>
              ))}
            </div>
            <div className="transport">
              <button className="playbtn">▶</button>
              <div className="scrub">
                <div className="fill"></div>
              </div>
              <span className="time mono">15:04 / {meta.duration}</span>
            </div>
          </div>
          <div className="transcript">
            {detail.transcript.map((row, i) => (
              <div className={"tline" + (row[2] ? " current" : "")} key={i}>
                <span className="tc mono">{row[0]}</span>
                <span>{row[1]}</span>
              </div>
            ))}
          </div>
        </div>
        <div className="panel">
          <h3>Notes</h3>
          <div className="notes-area" contentEditable suppressContentEditableWarning key={sessionId}>
            {detail.notes}
          </div>
          <div className="indexed-tag">✓ indexed — searchable in Q&A and artifacts</div>
        </div>
      </div>
    </section>
  );
}
