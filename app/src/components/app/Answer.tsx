import { useState, type ReactNode } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import { open } from "@tauri-apps/plugin-shell";
import type { Citation, MemoryUsed } from "../../sidecar";

// Must match chat.py's GENERAL_KNOWLEDGE_LABEL: the model starts the part of
// its answer that isn't from the course with this exact line.
const GENERAL_KNOWLEDGE_LABEL = "General knowledge (not from your course materials):";

// chat.py's CitationRenumberer rewrites the model's markers to [1], [2]… in
// the order they first appear, which is also the order of the citations list
// sent after the answer. [1, 3] is two markers.
const CITATION = /[ \t]?\[(\d+(?:\s*,\s*\d+)*)\]/g;

const SOURCE_KIND: Record<Citation["source_type"], string> = {
  page: "Canvas page",
  file: "File",
  syllabus: "Syllabus",
  assignment: "Assignment",
  transcript: "Recording",
  notes: "Your notes",
};

// Minimal hast shape: enough to walk text nodes without depending on the
// hast types react-markdown happens to install.
interface HastNode {
  type: string;
  value?: string;
  tagName?: string;
  properties?: Record<string, unknown>;
  children?: HastNode[];
}

function splitCitations(text: string): HastNode[] {
  const out: HastNode[] = [];
  let last = 0;
  for (const m of text.matchAll(CITATION)) {
    if (m.index > last) out.push({ type: "text", value: text.slice(last, m.index) });
    for (const n of m[1].split(",")) {
      const num = n.trim();
      out.push({ type: "element", tagName: "sup", properties: { dataCite: num }, children: [{ type: "text", value: num }] });
    }
    last = m.index + m[0].length;
  }
  if (last < text.length) out.push({ type: "text", value: text.slice(last) });
  return out;
}

function walk(node: HastNode) {
  if (!node.children || node.tagName === "code" || node.tagName === "pre") return;
  node.children = node.children.flatMap((child) => {
    if (child.type === "text" && child.value) return splitCitations(child.value);
    walk(child);
    return [child];
  });
}

// Rehype plugin: turns [n] markers in the rendered answer into <sup data-cite>.
function footnoteMarkers() {
  return (tree: HastNode) => walk(tree);
}

export function stripCitations(answer: string): string {
  return answer.replace(CITATION, "");
}

export default function Answer({
  answer,
  citations,
  grounded,
  memoriesUsed,
  onOpenCitation,
  actions,
}: {
  answer: string;
  citations: Citation[];
  grounded: boolean;
  memoriesUsed: MemoryUsed[];
  onOpenCitation: (c: Citation) => void;
  actions?: ReactNode;
}) {
  // The footnote number and its source row light up together.
  const [lit, setLit] = useState<number | null>(null);
  const sources = grounded ? citations : [];

  const components: Components = {
    sup({ node: _node, children, ...rest }) {
      const n = Number((rest as Record<string, unknown>)["data-cite"]);
      const source = sources[n - 1];
      if (!n) return <sup>{children}</sup>;
      // While streaming, the citations list hasn't arrived yet.
      if (!source) return <sup className="fn">{n}</sup>;
      return (
        <sup>
          <button
            type="button"
            className={"fn" + (lit === n ? " lit" : "")}
            aria-label={`Source ${n}: ${source.label}`}
            title={source.label}
            onMouseEnter={() => setLit(n)}
            onMouseLeave={() => setLit(null)}
            onFocus={() => setLit(n)}
            onBlur={() => setLit(null)}
            onClick={() => onOpenCitation(source)}
          >
            {n}
          </button>
        </sup>
      );
    },
    // A plain link would navigate the app's own window away from Second Mind.
    a({ node: _node, href, children }) {
      return (
        <a
          href={href}
          onClick={(e) => {
            e.preventDefault();
            if (href && /^https?:\/\//.test(href)) void open(href);
          }}
        >
          {children}
        </a>
      );
    },
  };

  const markdown = (text: string) => (
    <ReactMarkdown rehypePlugins={[footnoteMarkers]} components={components}>
      {text}
    </ReactMarkdown>
  );

  const at = answer.indexOf(GENERAL_KNOWLEDGE_LABEL);
  const course = (at === -1 ? answer : answer.slice(0, at)).trim();
  const general = at === -1 ? null : answer.slice(at + GENERAL_KNOWLEDGE_LABEL.length).trim();

  return (
    <>
      {course && <div className="qa-body">{markdown(course)}</div>}
      {general !== null && (
        <div className="qa-general">
          <div className="qa-general-head">General knowledge · not from your course</div>
          {general && <div className="qa-body">{markdown(general)}</div>}
        </div>
      )}
      {sources.length > 0 && (
        <ol className="qa-notes" aria-label="Sources">
          {sources.map((c, i) => (
            <li key={i} className={lit === i + 1 ? "lit" : undefined}>
              <button
                type="button"
                onMouseEnter={() => setLit(i + 1)}
                onMouseLeave={() => setLit(null)}
                onFocus={() => setLit(i + 1)}
                onBlur={() => setLit(null)}
                onClick={() => onOpenCitation(c)}
              >
                <span className="n">{i + 1}</span>
                <span className="src">{c.label}</span>
                <span className="kind">{SOURCE_KIND[c.source_type] ?? "Source"}</span>
              </button>
            </li>
          ))}
        </ol>
      )}
      {memoriesUsed.length > 0 && (
        <div className="qa-memories">
          <span>Used what you told me earlier</span>
          {memoriesUsed.map((m) => (
            <span className="memory-chip" key={m.id}>
              {m.text}
            </span>
          ))}
        </div>
      )}
      {actions}
    </>
  );
}
