import { open } from "@tauri-apps/plugin-shell";
import type { Citation } from "./sidecar";

// Citation click-through (implementation-plan.md's UI feedback round):
// a "transcript"/"notes" citation's item_id is the real session_id
// (indexing.py's _with_ref_doc, Step 12) — navigate in-app. Everything
// else is Canvas course material, whose item_id is the real Canvas
// content id, opened in the system browser via the same web-preview URL
// Canvas itself uses. "file" is the only Canvas-material item_type
// actually reachable today (generation.py: real Canvas sync/ingestion —
// implementation-plan.md Step 11 — is deferred, so "page" is unreached);
// this still opens the right URL shape for it once that lands.
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
  await open(`${origin}/courses/${courseId}/files/${citation.item_id}`);
}
