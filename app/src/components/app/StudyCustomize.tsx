import { useEffect, useRef, useState } from "react";
import {
  DEFAULT_STUDY_OPTIONS,
  listStudySources,
  type StudyCount,
  type StudyDifficulty,
  type StudyKind,
  type StudyOptions,
  type StudySource,
} from "../../sidecar";

// NotebookLM's customize dialog: how many, how hard, and a topic. Plus which
// of the course's indexed sources to use, which NotebookLM does with its
// source checkboxes.

const SOURCE_KIND: Record<StudySource["source_type"], string> = {
  page: "Canvas page",
  file: "File",
  syllabus: "Syllabus",
  assignment: "Assignment",
  transcript: "Recording",
  notes: "Your notes",
};

function Segmented<T extends string>({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: T;
  options: { value: T; label: string }[];
  onChange: (value: T) => void;
}) {
  return (
    <div className="field">
      <span className="field-label">{label}</span>
      <div className="seg" role="radiogroup" aria-label={label}>
        {options.map((o) => (
          <button
            key={o.value}
            type="button"
            role="radio"
            aria-checked={value === o.value}
            className={value === o.value ? "on" : ""}
            onClick={() => onChange(o.value)}
          >
            {o.label}
          </button>
        ))}
      </div>
    </div>
  );
}

export default function StudyCustomize({
  courseId,
  kind,
  onCancel,
  onGenerate,
}: {
  courseId: number;
  kind: StudyKind;
  onCancel: () => void;
  onGenerate: (options: StudyOptions) => void;
}) {
  const [count, setCount] = useState<StudyCount>(DEFAULT_STUDY_OPTIONS.count);
  const [difficulty, setDifficulty] = useState<StudyDifficulty>(DEFAULT_STUDY_OPTIONS.difficulty);
  const [topic, setTopic] = useState("");
  const [chooseSources, setChooseSources] = useState(false);
  const [sources, setSources] = useState<StudySource[] | null>(null);
  const [sourcesError, setSourcesError] = useState<string | null>(null);
  const [chosen, setChosen] = useState<Set<string>>(new Set());
  const dialogRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    dialogRef.current?.querySelector<HTMLElement>("textarea")?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onCancel();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onCancel]);

  useEffect(() => {
    if (!chooseSources || sources) return;
    listStudySources(courseId)
      .then(setSources)
      .catch((err) => setSourcesError(err instanceof Error ? err.message : "Couldn't load sources"));
  }, [chooseSources, sources, courseId]);

  function toggle(ids: string[], on: boolean) {
    setChosen((prev) => {
      const next = new Set(prev);
      for (const id of ids) {
        if (on) next.add(id);
        else next.delete(id);
      }
      return next;
    });
  }

  // In the backend's order, which is Canvas's: Week 01, Week 02, …
  const groups: { name: string; sources: StudySource[] }[] = [];
  for (const s of sources ?? []) {
    const last = groups[groups.length - 1];
    if (last?.name === s.group) last.sources.push(s);
    else groups.push({ name: s.group, sources: [s] });
  }

  const noun = kind === "quiz" ? "questions" : "cards";
  const canGenerate = !chooseSources || chosen.size > 0;

  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onCancel()}>
      <div className="modal" role="dialog" aria-modal="true" aria-labelledby="study-customize-title" ref={dialogRef}>
        <h2 id="study-customize-title">Customize {kind === "quiz" ? "quiz" : "flashcards"}</h2>
        <div className="modal-row">
          <Segmented
            label={`Number of ${noun}`}
            value={count}
            onChange={setCount}
            options={[
              { value: "fewer", label: "Fewer" },
              { value: "standard", label: "Standard" },
              { value: "more", label: "More" },
            ]}
          />
          <Segmented
            label="Level of difficulty"
            value={difficulty}
            onChange={setDifficulty}
            options={[
              { value: "easy", label: "Easy" },
              { value: "medium", label: "Medium" },
              { value: "hard", label: "Hard" },
            ]}
          />
        </div>
        <div className="field">
          <label htmlFor="study-topic">What should the topic be?</label>
          <textarea
            id="study-topic"
            className="modal-textarea"
            rows={3}
            maxLength={500}
            value={topic}
            placeholder={
              kind === "quiz"
                ? "For example: only cover test doubles from this week's lecture, and focus on when to use each one"
                : "For example: key terms from the last two lectures"
            }
            onChange={(e) => setTopic(e.target.value)}
          />
        </div>
        <div className="field">
          <span className="field-label">Sources</span>
          <div className="seg" role="radiogroup" aria-label="Sources">
            <button type="button" role="radio" aria-checked={!chooseSources} className={chooseSources ? "" : "on"} onClick={() => setChooseSources(false)}>
              All course material
            </button>
            <button type="button" role="radio" aria-checked={chooseSources} className={chooseSources ? "on" : ""} onClick={() => setChooseSources(true)}>
              Choose sources
            </button>
          </div>
          {chooseSources && (
            <div className="source-list">
              {sourcesError && <p className="qa-a-error">{sourcesError}</p>}
              {!sources && !sourcesError && <p className="qa-thinking">Loading sources…</p>}
              {sources?.length === 0 && <p className="qa-empty">Nothing is indexed for this course yet.</p>}
              {groups.map((g) => {
                const ids = g.sources.map((s) => s.item_id);
                const picked = ids.filter((id) => chosen.has(id)).length;
                return (
                  <div className="source-group" key={g.name}>
                    <label className="source-option source-group-head">
                      <input
                        type="checkbox"
                        checked={picked === ids.length}
                        ref={(el) => {
                          if (el) el.indeterminate = picked > 0 && picked < ids.length;
                        }}
                        onChange={(e) => toggle(ids, e.target.checked)}
                      />
                      <span className="src">{g.name}</span>
                      <span className="kind">{ids.length}</span>
                    </label>
                    {g.sources.map((s) => (
                      <label className="source-option source-child" key={s.item_id}>
                        <input type="checkbox" checked={chosen.has(s.item_id)} onChange={(e) => toggle([s.item_id], e.target.checked)} />
                        <span className="src">{s.source}</span>
                        <span className="kind">{SOURCE_KIND[s.source_type] ?? s.source_type}</span>
                      </label>
                    ))}
                  </div>
                );
              })}
            </div>
          )}
        </div>
        <div className="modal-actions">
          <button type="button" className="btn-secondary" onClick={onCancel}>
            Cancel
          </button>
          <button
            type="button"
            className="btn-primary"
            disabled={!canGenerate}
            onClick={() =>
              onGenerate({ count, difficulty, topic: topic.trim(), item_ids: chooseSources ? [...chosen] : null })
            }
          >
            Generate
          </button>
        </div>
      </div>
    </div>
  );
}
