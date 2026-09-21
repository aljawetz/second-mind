export default function Topbar({
  courseCode,
  courseName,
  overrideTitle,
}: {
  courseCode: string;
  courseName: string;
  overrideTitle?: string;
}) {
  if (overrideTitle) {
    return (
      <div className="topbar">
        <h1>{overrideTitle}</h1>
      </div>
    );
  }

  return (
    <div className="topbar">
      <h1>{courseCode}</h1>
      <span className="code mono">{courseName}</span>
    </div>
  );
}
