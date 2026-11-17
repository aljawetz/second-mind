import { useEffect, useState } from "react";
import type { AvailableCourse } from "../../types";
import { listLargeFiles, setLargeFileFull, syncCourse, type LargeFile } from "../../sidecar";

// Long files are synced as a preview and files over 50 MB not at all
// (backend/large_files.py), so a first sync doesn't spend minutes on whole
// textbooks. Here the student can sync any of them in full; the course is
// synced again right away rather than at the next launch.

function details(f: LargeFile): string {
  const parts = [];
  if (f.pages) parts.push(`${f.pages} pages`);
  parts.push(`${Math.max(1, Math.round(f.size / 1_000_000))} MB`);
  return parts.join(" · ");
}

function status(f: LargeFile): string {
  if (f.state === "full") return "Whole file synced";
  if (f.state === "none") return "Not synced (over 50 MB)";
  return f.pages ? "First 150 pages synced" : "First part synced";
}

export default function LargeFilesSection({ courses }: { courses: AvailableCourse[] }) {
  const [files, setFiles] = useState<Record<number, LargeFile[]>>({});
  const [busy, setBusy] = useState<string | null>(null); // "<courseId>:<fileId>" while syncing
  const [error, setError] = useState("");

  async function load(courseId: number) {
    try {
      const list = await listLargeFiles(courseId);
      setFiles((prev) => ({ ...prev, [courseId]: list }));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't load large files");
    }
  }

  useEffect(() => {
    courses.forEach((c) => void load(c.id));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [courses.map((c) => c.id).join(",")]);

  async function toggle(courseId: number, f: LargeFile) {
    setBusy(`${courseId}:${f.file_id}`);
    setError("");
    try {
      await setLargeFileFull(courseId, f.file_id, !f.want_full);
      let syncError: string | null = null;
      await syncCourse(courseId, (event) => {
        if (event.done && event.error) syncError = event.error;
        else if (event.status === "failed" && event.item === f.name) syncError = event.error ?? "sync failed";
      });
      if (syncError) setError(`${f.name}: ${syncError}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't sync this file");
    } finally {
      await load(courseId);
      setBusy(null);
    }
  }

  const withFiles = courses.filter((c) => (files[c.id] ?? []).length > 0);
  if (withFiles.length === 0 && !error) return null;

  return (
    <div className="home-block">
      <div className="section-label">Large files</div>
      <p className="qa-empty">
        Long files are synced as a preview, and files over 50 MB aren't synced, so the first sync stays quick.
        Sync a whole file when you need all of it. A textbook can take a few minutes.
      </p>
      {error && <p className="qa-a-error">{error}</p>}
      {withFiles.map((c) => (
        <div className="course-pick" key={c.id}>
          {(files[c.id] ?? []).map((f) => {
            const key = `${c.id}:${f.file_id}`;
            return (
              <div className="course-row" key={key}>
                <span className="cmeta">
                  <div className="ccode">
                    {c.code} · {details(f)} · {busy === key ? "Syncing…" : status(f)}
                  </div>
                  <div className="cname">{f.name}</div>
                </span>
                <span className="manage-actions">
                  <button className="icon-btn" disabled={busy !== null} onClick={() => void toggle(c.id, f)}>
                    {!f.want_full ? "Sync whole file" : f.size > 50_000_000 ? "Don't sync" : "Back to preview"}
                  </button>
                </span>
              </div>
            );
          })}
        </div>
      ))}
    </div>
  );
}
