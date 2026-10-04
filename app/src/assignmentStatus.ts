import type { CanvasAssignment } from "./sidecar";

export function formatDue(dueAt: string | null): string {
  if (!dueAt) return "No due date";
  return new Date(dueAt).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

// "Past/completed" combines two real signals: Canvas's own submission
// status (not a guess from due date — a submitted assignment counts even
// if turned in early) and, for anything not yet submitted, whether its due
// date has already passed.
export function isPastOrCompleted(a: CanvasAssignment, now: number): boolean {
  if (a.submitted) return true;
  return !!a.due_at && new Date(a.due_at).getTime() < now;
}

export function splitAssignments(assignments: CanvasAssignment[]): {
  upcoming: CanvasAssignment[];
  past: CanvasAssignment[];
} {
  const now = Date.now();
  const upcoming: CanvasAssignment[] = [];
  const past: CanvasAssignment[] = [];
  for (const a of assignments) (isPastOrCompleted(a, now) ? past : upcoming).push(a);

  // Undated assignments sort last in both lists rather than being dropped.
  upcoming.sort((a, b) => {
    if (!a.due_at) return b.due_at ? 1 : 0;
    if (!b.due_at) return -1;
    return new Date(a.due_at).getTime() - new Date(b.due_at).getTime();
  });
  past.sort((a, b) => {
    if (!a.due_at) return b.due_at ? 1 : 0;
    if (!b.due_at) return -1;
    return new Date(b.due_at).getTime() - new Date(a.due_at).getTime();
  });
  return { upcoming, past };
}

// Calendar days from today to the due date, in local time: 0 is today.
function daysUntil(dueAt: string): number {
  const due = new Date(dueAt);
  due.setHours(0, 0, 0, 0);
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  return Math.round((due.getTime() - today.getTime()) / 86_400_000);
}

export function statusPill(a: CanvasAssignment): { text: string; cls: string } {
  if (a.missing) return { text: "Missing", cls: "pill-red" };
  if (a.submitted) return { text: a.late ? "Submitted late" : "Submitted", cls: "pill-green" };
  if (!a.due_at) return { text: "No due date", cls: "pill-neutral" };
  // Work due within a day gets the urgent colour.
  const days = daysUntil(a.due_at);
  if (days === 0) return { text: "Due today", cls: "pill-red" };
  if (days === 1) return { text: "Due tomorrow", cls: "pill-red" };
  return { text: `Due ${formatDue(a.due_at)}`, cls: "pill-ochre" };
}
