import { open } from "@tauri-apps/plugin-shell";
import type { Citation } from "./sidecar";

// Citation click-through (implementation-plan.md's UI feedback round):
// a "transcript"/"notes" citation's item_id is the real session_id
// (indexing.py's _with_ref_doc, Step 12) — navigate in-app. Everything
// else is Canvas course material, opened in the system browser via the
// same web URL Canvas itself uses. Both "file" and "page" citations are
// live now that course_sync.py indexes real Canvas files and wiki pages,
// and they take different URL shapes (/files/{id} vs /pages/{url}).
//
// course_sync.py prefixes every indexed item's id by type ("file:12345",
// "page:week-1-overview") — files and pages share one flat ref_doc_id
// namespace per course table — and that prefixed id is what arrives here
// as citation.item_id, so the prefix has to come back off before it goes
// into a URL.
//
// canvasBaseUrl comes from the student's own configured Canvas origin
// (config.json's canvas_base_url, set during onboarding) — never a
// hardcoded domain; SSB only ever worked against canvas.cmu.edu before
// contribution-and-distribution-plan.md step 2. Falls back to CMU's
// Canvas only if config genuinely hasn't loaded yet, matching canvas.py's
// own default.
export async function openCitation(
  canvasBaseUrl: string,
  courseId: number,
  citation: Citation,
  onOpenSession: (sessionId: string) => void
): Promise<void> {
  if (citation.source_type === "transcript" || citation.source_type === "notes") {
    onOpenSession(citation.item_id);
    return;
  }
  const origin = canvasBaseUrl || "https://canvas.cmu.edu";
  if (citation.source_type === "page") {
    const pageUrl = citation.item_id.replace(/^page:/, "");
    await open(`${origin}/courses/${courseId}/pages/${pageUrl}`);
    return;
  }
  const fileId = citation.item_id.replace(/^file:/, "");
  await open(`${origin}/courses/${courseId}/files/${fileId}`);
}
