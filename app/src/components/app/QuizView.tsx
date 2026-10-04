import { useEffect, useState } from "react";
import { getStudy, saveStudyProgress, type Citation, type QuizQuestion, type StudyArtifact } from "../../sidecar";

// A quiz the way NotebookLM runs one: one question at a time, a hint before
// answering, a short explanation of the right and the chosen answer after,
// Explain for more (in the course chat, cited), and at the end a score with
// Review answers and Try again. Answers are saved as they're given, so the
// quiz picks up where it was left.

const LETTERS = "ABCD";

export function explainQuizPrompt(q: QuizQuestion, chosen: number | undefined): string {
  const right = q.options.find((o) => o.correct)?.text ?? "";
  let text = `Explain this quiz question: "${q.question}" The correct answer is "${right}".`;
  if (chosen !== undefined && !q.options[chosen].correct) {
    text += ` I answered "${q.options[chosen].text}". Why is that wrong?`;
  }
  return text;
}

export default function QuizView({
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
  const [quiz, setQuiz] = useState<StudyArtifact | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [answers, setAnswers] = useState<Record<string, number>>({});
  const [position, setPosition] = useState(0);
  const [finished, setFinished] = useState(false);
  const [hintOpen, setHintOpen] = useState(false);

  useEffect(() => {
    let cancelled = false;
    getStudy(courseId, artifactId)
      .then((q) => {
        if (cancelled) return;
        setQuiz(q);
        setAnswers(q.progress.answers ?? {});
        setPosition(Math.min(q.progress.position ?? 0, q.items.length - 1));
        setFinished(!!q.progress.finished);
      })
      .catch((err) => !cancelled && setLoadError(err instanceof Error ? err.message : "Couldn't open this quiz"));
    return () => {
      cancelled = true;
    };
  }, [courseId, artifactId]);

  function save(next: { answers?: Record<string, number>; position?: number; finished?: boolean }) {
    // Best effort: losing a saved position isn't worth interrupting the quiz for.
    void saveStudyProgress(courseId, artifactId, { answers, position, finished, ...next }).catch(() => {});
  }

  const questions = (quiz?.items ?? []) as QuizQuestion[];
  const q = questions[position];
  const chosen = answers[String(position)];
  const answered = chosen !== undefined;

  function go(to: number) {
    setPosition(to);
    setHintOpen(false);
    save({ position: to });
  }

  function choose(i: number) {
    if (answered) return;
    const next = { ...answers, [String(position)]: i };
    setAnswers(next);
    save({ answers: next });
  }

  function finish() {
    setFinished(true);
    save({ finished: true });
  }

  function restart(keepAnswers: boolean) {
    const next = keepAnswers ? answers : {};
    setAnswers(next);
    setFinished(false);
    setPosition(0);
    setHintOpen(false);
    save({ answers: next, position: 0, finished: false });
  }

  // ←/→ move between questions, 1–4 or A–D answer.
  useEffect(() => {
    if (!quiz || finished) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLElement && e.target.closest("input, textarea")) return;
      if (e.key === "ArrowRight" && position < questions.length - 1) go(position + 1);
      else if (e.key === "ArrowLeft" && position > 0) go(position - 1);
      else {
        const i = "1234".indexOf(e.key) >= 0 ? "1234".indexOf(e.key) : "abcd".indexOf(e.key.toLowerCase());
        if (i >= 0 && e.key.length === 1) choose(i);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  const correct = questions.filter((qq, i) => {
    const a = answers[String(i)];
    return a !== undefined && qq.options[a]?.correct;
  }).length;
  const attempted = Object.keys(answers).length;
  const skipped = questions.length - attempted;

  return (
    <section className="study-view">
      <button className="back-link" onClick={onBack}>
        ‹ Course home
      </button>
      {loadError && <p className="qa-a-error">{loadError}</p>}
      {!quiz && !loadError && <p className="qa-thinking">Opening…</p>}
      {quiz && (
        <>
          <div className="study-head">
            <h2>{quiz.title}</h2>
            <span className="study-sub">
              Quiz · {quiz.options.difficulty[0].toUpperCase() + quiz.options.difficulty.slice(1)} · {questions.length} questions
            </span>
          </div>

          {finished ? (
            <div className="study-card quiz-results">
              <h3>Your results</h3>
              <div className="score">
                {correct} / {questions.length}
              </div>
              <dl className="result-stats">
                <div>
                  <dt>Accuracy</dt>
                  <dd>{attempted ? Math.round((correct / attempted) * 100) : 0}%</dd>
                </div>
                <div>
                  <dt>Correct</dt>
                  <dd className="ok">{correct}</dd>
                </div>
                <div>
                  <dt>Incorrect</dt>
                  <dd className="bad">{attempted - correct}</dd>
                </div>
                <div>
                  <dt>Skipped</dt>
                  <dd>{skipped}</dd>
                </div>
              </dl>
              <div className="study-actions center">
                <button type="button" className="btn-secondary" onClick={() => restart(true)}>
                  Review answers
                </button>
                <button type="button" className="btn-primary" onClick={() => restart(false)}>
                  Try again
                </button>
              </div>
            </div>
          ) : (
            q && (
              <>
                <div className="study-progress" aria-label={`Question ${position + 1} of ${questions.length}`}>
                  <span>
                    {position + 1} / {questions.length}
                  </span>
                  <div className="bar">
                    <div style={{ width: `${((position + 1) / questions.length) * 100}%` }} />
                  </div>
                </div>
                <div className="study-card">
                  <p className="quiz-q">{q.question}</p>
                  <ol className="quiz-options">
                    {q.options.map((o, i) => {
                      const state = !answered ? "" : o.correct ? " right" : i === chosen ? " wrong" : " dim";
                      const showWhy = answered && (o.correct || i === chosen) && o.rationale;
                      return (
                        <li key={i}>
                          <button type="button" className={"quiz-option" + state} disabled={answered} onClick={() => choose(i)}>
                            <span className="letter">{LETTERS[i]}</span>
                            <span className="txt">{o.text}</span>
                            {answered && o.correct && <span className="verdict">Right answer</span>}
                            {answered && i === chosen && !o.correct && <span className="verdict">Not quite</span>}
                          </button>
                          {showWhy && <p className="quiz-why">{o.rationale}</p>}
                        </li>
                      );
                    })}
                  </ol>
                  {!answered && q.hint && (
                    <div className="quiz-hint">
                      <button type="button" className="link-btn" aria-expanded={hintOpen} onClick={() => setHintOpen((o) => !o)}>
                        {hintOpen ? "Hide hint" : "Hint"}
                      </button>
                      {hintOpen && <p>{q.hint}</p>}
                    </div>
                  )}
                  {answered && (
                    <div className="study-source">
                      <span>Source</span>
                      <button type="button" className="cite cite-link" onClick={() => onOpenCitation(q.citation)}>
                        {q.citation.label}
                      </button>
                    </div>
                  )}
                </div>
                <div className="study-actions">
                  <button type="button" className="btn-secondary" disabled={position === 0} onClick={() => go(position - 1)}>
                    ‹ Previous
                  </button>
                  <button
                    type="button"
                    className="btn-secondary explain"
                    disabled={!answered}
                    title={answered ? undefined : "Answer first"}
                    onClick={() => onExplain(explainQuizPrompt(q, chosen))}
                  >
                    ✦ Explain
                  </button>
                  {position < questions.length - 1 ? (
                    <button type="button" className="btn-primary" onClick={() => go(position + 1)}>
                      Next ›
                    </button>
                  ) : (
                    <button type="button" className="btn-primary" onClick={finish}>
                      Finish
                    </button>
                  )}
                </div>
              </>
            )
          )}
        </>
      )}
    </section>
  );
}
