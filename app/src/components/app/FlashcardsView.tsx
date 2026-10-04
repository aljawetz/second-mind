import { useEffect, useState } from "react";
import {
  exportStudyCsv,
  getStudy,
  saveStudyProgress,
  type Citation,
  type Flashcard,
  type FlashcardProgress,
  type StudyArtifact,
} from "../../sidecar";

// Flashcards the way NotebookLM runs them: flip a card, Got it / Missed it,
// Previous / Next, Shuffle, Delete a card, Explain (in the course chat,
// cited), and at the end practise the same cards, all cards, or only the
// ones missed. Progress is saved as it changes.

export function explainCardPrompt(card: Flashcard): string {
  return `Explain this flashcard. Front: "${card.front}" Back: "${card.back}"`;
}

function shuffled(list: number[]): number[] {
  const out = [...list];
  for (let i = out.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [out[i], out[j]] = [out[j], out[i]];
  }
  return out;
}

export default function FlashcardsView({
  courseId,
  artifactId,
  onBack,
  onExplain,
  onOpenCitation,
}: {
  courseId: number;
  artifactId: string;
  onBack: () => void;
  onExplain: (prompt: string) => void;
  onOpenCitation: (c: Citation) => void;
}) {
  const [deck, setDeck] = useState<StudyArtifact | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [progress, setProgress] = useState<Required<FlashcardProgress>>({ position: 0, marks: {}, removed: [], order: [] });
  const [flipped, setFlipped] = useState(false);
  const [atEnd, setAtEnd] = useState(false);
  const [exported, setExported] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getStudy(courseId, artifactId)
      .then((d) => {
        if (cancelled) return;
        const removed = d.progress.removed ?? [];
        const all = d.items.map((_, i) => i).filter((i) => !removed.includes(i));
        const order = (d.progress.order ?? all).filter((i) => !removed.includes(i) && i < d.items.length);
        setDeck(d);
        setProgress({
          position: Math.min(d.progress.position ?? 0, Math.max(order.length - 1, 0)),
          marks: d.progress.marks ?? {},
          removed,
          order: order.length ? order : all,
        });
      })
      .catch((err) => !cancelled && setLoadError(err instanceof Error ? err.message : "Couldn't open these flashcards"));
    return () => {
      cancelled = true;
    };
  }, [courseId, artifactId]);

  function update(next: Partial<FlashcardProgress>) {
    const merged = { ...progress, ...next };
    setProgress(merged);
    // Best effort: losing a saved position isn't worth interrupting practice for.
    void saveStudyProgress(courseId, artifactId, merged).catch(() => {});
  }

  const cards = (deck?.items ?? []) as Flashcard[];
  const { order, position, marks } = progress;
  const index = order[position];
  const card = index !== undefined ? cards[index] : undefined;

  function go(to: number) {
    setFlipped(false);
    if (to >= order.length) {
      setAtEnd(true);
      return;
    }
    update({ position: Math.max(0, to) });
  }

  function mark(m: "got" | "missed") {
    if (index === undefined) return;
    setFlipped(false);
    const nextMarks = { ...marks, [String(index)]: m };
    if (position + 1 >= order.length) {
      update({ marks: nextMarks });
      setAtEnd(true);
    } else {
      update({ marks: nextMarks, position: position + 1 });
    }
  }

  function removeCard() {
    if (index === undefined) return;
    const nextOrder = order.filter((i) => i !== index);
    setFlipped(false);
    update({ removed: [...progress.removed, index], order: nextOrder, position: Math.min(position, Math.max(nextOrder.length - 1, 0)) });
  }

  function practise(which: "same" | "all" | "missed") {
    const all = cards.map((_, i) => i).filter((i) => !progress.removed.includes(i));
    const nextOrder = which === "same" ? order : which === "all" ? all : order.filter((i) => marks[String(i)] === "missed");
    setAtEnd(false);
    setFlipped(false);
    update({ order: nextOrder, position: 0, marks: {} });
  }

  async function download() {
    try {
      setExported(`Saved to ${await exportStudyCsv(courseId, artifactId)}`);
    } catch (err) {
      setExported(err instanceof Error ? err.message : "Couldn't save the file");
    }
  }

  // Space flips, ←/→ move.
  useEffect(() => {
    if (!deck || atEnd) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLElement && e.target.closest("input, textarea, button")) return;
      if (e.key === " ") {
        e.preventDefault();
        setFlipped((f) => !f);
      } else if (e.key === "ArrowRight") go(position + 1);
      else if (e.key === "ArrowLeft" && position > 0) go(position - 1);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  const got = order.filter((i) => marks[String(i)] === "got").length;
  const missed = order.filter((i) => marks[String(i)] === "missed").length;

  return (
    <section className="study-view">
      <button className="back-link" onClick={onBack}>
        ‹ Course home
      </button>
      {loadError && <p className="qa-a-error">{loadError}</p>}
      {!deck && !loadError && <p className="qa-thinking">Opening…</p>}
      {deck && (
        <>
          <div className="study-head">
            <h2>{deck.title}</h2>
            <span className="study-sub">
              Flashcards · {deck.options.difficulty[0].toUpperCase() + deck.options.difficulty.slice(1)} · {order.length} cards
            </span>
            <div className="study-tools">
              <button type="button" className="icon-btn" title="Shuffle" aria-label="Shuffle" disabled={atEnd} onClick={() => update({ order: shuffled(order), position: 0 })}>
                <svg viewBox="0 0 24 24" aria-hidden="true">
                  <path d="M16 3h5v5M4 20 21 3M21 16v5h-5M15 15l6 6M4 4l5 5" />
                </svg>
              </button>
              <button type="button" className="icon-btn" title="Download as CSV" aria-label="Download as CSV" onClick={() => void download()}>
                <svg viewBox="0 0 24 24" aria-hidden="true">
                  <path d="M12 3v12m0 0-4-4m4 4 4-4M4 17v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2" />
                </svg>
              </button>
              <button type="button" className="icon-btn icon-btn-danger" title="Delete this card" aria-label="Delete this card" disabled={atEnd || !card} onClick={removeCard}>
                <svg viewBox="0 0 24 24" aria-hidden="true">
                  <path d="M3 6h18M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                </svg>
              </button>
            </div>
          </div>
          {exported && <p className="study-note">{exported}</p>}

          {atEnd || !card ? (
            <div className="study-card quiz-results">
              <h3>{order.length ? "You've been through the deck" : "No cards left"}</h3>
              <dl className="result-stats">
                <div>
                  <dt>Got it</dt>
                  <dd className="ok">{got}</dd>
                </div>
                <div>
                  <dt>Missed it</dt>
                  <dd className="bad">{missed}</dd>
                </div>
                <div>
                  <dt>Not marked</dt>
                  <dd>{order.length - got - missed}</dd>
                </div>
              </dl>
              <div className="study-actions center">
                <button type="button" className="btn-secondary" disabled={!order.length} onClick={() => practise("same")}>
                  Same cards
                </button>
                <button type="button" className="btn-secondary" onClick={() => practise("all")}>
                  All cards
                </button>
                <button type="button" className="btn-primary" disabled={!missed} onClick={() => practise("missed")}>
                  Only cards you missed
                </button>
              </div>
            </div>
          ) : (
            <>
              <div className="study-progress" aria-label={`Card ${position + 1} of ${order.length}`}>
                <span>
                  {position + 1} / {order.length}
                </span>
                <div className="bar">
                  <div style={{ width: `${((position + 1) / order.length) * 100}%` }} />
                </div>
              </div>
              <div className={"flashcard" + (flipped ? " flipped" : "")}>
                <button type="button" className="flashcard-face" aria-label={flipped ? "Show the front" : "Show the answer"} onClick={() => setFlipped((f) => !f)}>
                  <span className="side-name">{flipped ? "Answer" : "Front"}</span>
                  <span className="flashcard-text">{flipped ? card.back : card.front}</span>
                  {!flipped && <span className="flip-hint">Click or press space to see the answer</span>}
                </button>
                {flipped && (
                  <div className="study-source">
                    <span>Source</span>
                    <button type="button" className="cite cite-link" onClick={() => onOpenCitation(card.citation)}>
                      {card.citation.label}
                    </button>
                  </div>
                )}
              </div>
              <div className="study-actions">
                <button type="button" className="btn-secondary" disabled={position === 0} onClick={() => go(position - 1)}>
                  ‹ Previous
                </button>
                <button type="button" className="btn-secondary mark-missed" onClick={() => mark("missed")}>
                  ✗ Missed it
                </button>
                <button type="button" className="btn-secondary explain" onClick={() => onExplain(explainCardPrompt(card))}>
                  ✦ Explain
                </button>
                <button type="button" className="btn-secondary mark-got" onClick={() => mark("got")}>
                  ✓ Got it
                </button>
                <button type="button" className="btn-primary" onClick={() => go(position + 1)}>
                  Next ›
                </button>
              </div>
            </>
          )}
        </>
      )}
    </section>
  );
}
