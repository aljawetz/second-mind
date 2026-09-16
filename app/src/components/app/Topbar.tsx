import type { Course } from "../../types";

export default function Topbar({
  course,
  courseCode,
  socratic,
  onToggleSocratic,
}: {
  course: Course;
  courseCode: string;
  socratic: boolean;
  onToggleSocratic: () => void;
}) {
  return (
    <div className="topbar">
      <h1>{courseCode}</h1>
      <span className="code mono">{course.code}</span>
      <div className="topbar-right">
        <span className="pill">◆ grounded</span>
        <div className="toggle-wrap">
          <span>Socratic mode</span>
          <button
            className="toggle"
            aria-pressed={socratic}
            title="Toggle Socratic mode"
            onClick={onToggleSocratic}
          ></button>
        </div>
      </div>
    </div>
  );
}
