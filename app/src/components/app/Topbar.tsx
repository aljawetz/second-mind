import { useEffect, useRef, useState } from "react";
import { useDismissOnOutside } from "../../hooks/useDismissOnOutside";

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
  // detail: the full per-item failure list, opened from the status pill — the label
  // stays short enough for the pill.
  syncStatus?: { label: string; detail?: string; error?: boolean; ok?: boolean };
  onManageMemories?: () => void;
}) {
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  const [syncDetailsOpen, setSyncDetailsOpen] = useState(false);
  const syncDetailsRef = useRef<HTMLDivElement>(null);

  useDismissOnOutside(menuRef, menuOpen, () => setMenuOpen(false));
  useDismissOnOutside(syncDetailsRef, syncDetailsOpen, () => setSyncDetailsOpen(false));
  useEffect(() => {
    if (!syncStatus?.error) setSyncDetailsOpen(false);
  }, [syncStatus?.error]);

  useEffect(() => {
    if (!menuOpen) return;
    const id = requestAnimationFrame(() => {
      menuRef.current?.querySelector<HTMLElement>('[role="menuitem"]')?.focus();
    });
    return () => cancelAnimationFrame(id);
  }, [menuOpen]);

  const pill = syncStatus && (syncStatus.error && syncStatus.detail ? (
    <div className="sync-details-anchor" ref={syncDetailsRef}>
      <button className="sync-pill error" aria-expanded={syncDetailsOpen} onClick={() => setSyncDetailsOpen((open) => !open)}>
        <span className="label">{syncStatus.label}</span>
        <span className="sync-details-label">Details</span>
      </button>
      {syncDetailsOpen && <pre className="sync-details-panel">{syncStatus.detail}</pre>}
    </div>
  ) : (
    <span
      className={"sync" + (syncStatus.error ? " error" : syncStatus.ok ? " ok" : "")}
      title={syncStatus.detail || syncStatus.label}
    >
      <span className="label">{syncStatus.label}</span>
    </span>
  ));

  const courseMenu =
    onManageMemories &&
    !overrideTitle && (
      <div className="settings-anchor" ref={menuRef}>
        <button
          className="text-btn"
          aria-expanded={menuOpen}
          aria-haspopup="menu"
          onClick={() => setMenuOpen((o) => !o)}
        >
          Course options
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
      <span className="course-code">{courseCode}</span>
      <h1 title={courseName}>{courseName}</h1>
      {actions}
    </div>
  );
}
