export default function Topbar({
  courseCode,
  courseName,
  overrideTitle,
  syncStatus,
}: {
  courseCode: string;
  courseName: string;
  overrideTitle?: string;
  syncStatus?: { label: string; error?: boolean };
}) {
  const pill = syncStatus && (
    <span className={"pill ground-pill " + (syncStatus.error ? "pill-red" : "pill-neutral")} title={syncStatus.label}>
      {syncStatus.label}
    </span>
  );

  if (overrideTitle) {
    return (
      <div className="topbar">
        <h1>{overrideTitle}</h1>
        {pill}
      </div>
    );
  }

  return (
    <div className="topbar">
      <h1>{courseCode}</h1>
      <span className="code mono">{courseName}</span>
      {pill}
    </div>
  );
}
