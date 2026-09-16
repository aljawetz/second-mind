import type { ArtifactType, Course } from "../../types";
import { ARTIFACT_TYPES } from "../../data";

function groundLabel(course: Course, artifact: ArtifactType): string {
  if (artifact === "mocktest") return `${course.mocktest.length} / ${course.mocktest.length} sources verified`;
  if (artifact === "cards") return `${course.cards.length} / ${course.cards.length} sources verified`;
  if (artifact === "slides") return `${course.slides.length} slides`;
  return `derived from ${course.sessions.length} sessions`;
}

function Mindmap({ course }: { course: Course }) {
  const mm = course.mindmap;
  const cx = 130;
  const cy = 160;
  const r = 150;
  const angleStep = (2 * Math.PI) / mm.nodes.length;

  const nodes = mm.nodes.map((n, i) => {
    const ang = -Math.PI / 2 + i * angleStep + (mm.nodes.length === 4 ? Math.PI / 4 : 0);
    const nx = cx + r * 1.55 * Math.cos(ang);
    const ny = cy + r * 0.62 * Math.sin(ang) * 1.7 + 10;
    return { n, nx, ny };
  });

  return (
    <div className="mindmap">
      <svg viewBox="0 0 500 320" xmlns="http://www.w3.org/2000/svg">
        {nodes.map((node, i) => (
          <line key={i} className="mm-link" x1={cx} y1={cy} x2={node.nx} y2={node.ny}></line>
        ))}
        <g className="mm-node center">
          <rect x={cx - 70} y={cy - 22} width="140" height="44" rx="10"></rect>
          <text x={cx} y={cy + 5} textAnchor="middle" fontSize="13" fontWeight="600">
            {mm.center}
          </text>
        </g>
        {nodes.map((node, i) => (
          <g className="mm-node" key={i}>
            <rect x={node.nx - 62} y={node.ny - 18} width="124" height="36" rx="9"></rect>
            <text x={node.nx} y={node.ny + 5} textAnchor="middle" fontSize="12">
              {node.n}
            </text>
          </g>
        ))}
      </svg>
    </div>
  );
}

export default function ArtifactView({
  course,
  courseCode,
  artifact,
  onArtifactChange,
  onBack,
}: {
  course: Course;
  courseCode: string;
  artifact: ArtifactType;
  onArtifactChange: (type: ArtifactType) => void;
  onBack: () => void;
}) {
  const t = ARTIFACT_TYPES.find((x) => x.key === artifact)!;

  return (
    <section id="view-artifact">
      <button className="back-link" onClick={onBack}>
        ‹ Course home
      </button>
      <div className="artifact-head">
        <h2>
          {t.lbl} — {courseCode}
        </h2>
        <span className="pill ground-pill">{groundLabel(course, artifact)}</span>
      </div>
      <div className="tabs">
        {ARTIFACT_TYPES.map((x) => (
          <button
            key={x.key}
            className={"tab" + (x.key === artifact ? " active" : "")}
            onClick={() => onArtifactChange(x.key)}
          >
            {x.lbl}
          </button>
        ))}
      </div>

      {artifact === "mocktest" && (
        <div className="mocktest">
          {course.mocktest.map((m, i) => (
            <details className="mq" key={i}>
              <div className="qn mono">Q{i + 1}</div>
              <div className="qtext">{m.q}</div>
              <summary></summary>
              <div className="ans">
                {m.a}
                <div className="qa-sources" style={{ marginTop: ".5rem", paddingTop: ".4rem" }}>
                  <span className="cite">{m.src}</span>
                </div>
              </div>
            </details>
          ))}
        </div>
      )}

      {artifact === "cards" && (
        <div className="cardgrid">
          {course.cards.map((card, i) => (
            <label className="flip" key={i}>
              <input type="checkbox" />
              <div className="flip-inner">
                <div className="flip-face">
                  <div className="k">Front</div>
                  <div className="body">{card.front}</div>
                  <div className="flip-hint">tap to flip</div>
                </div>
                <div className="flip-face flip-back">
                  <div className="k">Back</div>
                  <div className="body">{card.back}</div>
                </div>
              </div>
            </label>
          ))}
        </div>
      )}

      {artifact === "slides" && (
        <div className="slidestrip">
          {course.slides.map((s, i) => (
            <div className="slide" key={i}>
              <div className="sn mono">SLIDE {s.n}</div>
              <h4>{s.title}</h4>
              <ul>
                {s.bullets.map((b, bi) => (
                  <li key={bi}>{b}</li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      )}

      {artifact === "mindmap" && <Mindmap course={course} />}
    </section>
  );
}
