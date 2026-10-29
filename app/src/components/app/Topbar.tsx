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
  // detail: the full per-item failure list, shown on hover — the label
  // stays short enough for one line.
  syncStatus?: { label: string; detail?: string; error?: boolean; ok?: boolean };
  onManageMemories?: () => void;
}) {
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);

  useDismissOnOutside(menuRef, menuOpen, () => setMenuOpen(false));

  useEffect(() => {
    if (!menuOpen) return;
    const id = requestAnimationFrame(() => {
      menuRef.current?.querySelector<HTMLElement>('[role="menuitem"]')?.focus();
    });
    return () => cancelAnimationFrame(id);
  }, [menuOpen]);

  const pill = syncStatus && (
    <span
      className={"sync" + (syncStatus.error ? " error" : syncStatus.ok ? " ok" : "")}
      title={syncStatus.detail || syncStatus.label}
    >
      <span className="label">{syncStatus.label}</span>
    </span>
  );

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
