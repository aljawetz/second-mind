import { useEffect, useRef, useState } from "react";

export default function Topbar({
  courseCode,
  courseName,
  overrideTitle,
  syncStatus,
  onManageMemories,
}: {
  courseCode: string;
  courseName: string;
  overrideTitle?: string;
  // detail: the full per-item failure list, shown on hover — the label
  // stays short enough for the pill.
  syncStatus?: { label: string; detail?: string; error?: boolean };
  onManageMemories?: () => void;
}) {
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!menuOpen) return;
    function handlePointerDown(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMenuOpen(false);
      }
    }
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") setMenuOpen(false);
    }
    document.addEventListener("mousedown", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("mousedown", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [menuOpen]);

  const pill = syncStatus && (
    <span
      className={"pill ground-pill " + (syncStatus.error ? "pill-red" : "pill-neutral")}
      title={syncStatus.detail || syncStatus.label}
    >
      {syncStatus.label}
    </span>
  );

  const courseMenu =
    onManageMemories &&
    !overrideTitle && (
      <div className="settings-anchor" ref={menuRef}>
        <button
          className="icon-btn"
          title="Course options"
          aria-label="Course options"
          aria-expanded={menuOpen}
          aria-haspopup="menu"
          onClick={() => setMenuOpen((o) => !o)}
        >
          <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
            <circle cx="12" cy="5" r="1.75"></circle>
            <circle cx="12" cy="12" r="1.75"></circle>
            <circle cx="12" cy="19" r="1.75"></circle>
          </svg>
        </button>
        {menuOpen && (
          <div className="settings-menu" role="menu">
            <button
              className="settings-menu-item"
              role="menuitem"
              onClick={() => {
                setMenuOpen(false);
                onManageMemories();
              }}
            >
              Manage memories
            </button>
          </div>
        )}
      </div>
    );

  const actions = (pill || courseMenu) && (
    <div className="topbar-actions">
      {pill}
      {courseMenu}
    </div>
  );

  if (overrideTitle) {
    return (
      <div className="topbar">
        <h1>{overrideTitle}</h1>
        {actions}
      </div>
    );
  }

  return (
    <div className="topbar">
      <h1>{courseCode}</h1>
      <span className="code mono">{courseName}</span>
      {actions}
    </div>
  );
}
