import { useEffect, useState } from "react";
import { getStudy, StudyMissing, type Citation, type QuizCardProps, type StudyArtifact } from "../../../sidecar";
import QuizView from "../QuizView";

// A practice quiz started from chat (backend show_quiz). It's a normal study
// artifact: written in the background with the grounding check, listed in
// the Study panel, progress saved the same way. Until it's written, this
// polls it, like the Study panel's list does.
const POLL_MS = 3000;

export default function QuizBlock({
  props,
  courseId,
  onOpenStudy,
  onExplain,
  onOpenCitation,
}: {
  props: QuizCardProps;
  courseId: number;
  onOpenStudy: (id: string) => void;
  onExplain: (prompt: string) => void;
  onOpenCitation: (c: Citation) => void;
}) {
  const [quiz, setQuiz] = useState<StudyArtifact | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const load = () => {
      getStudy(courseId, props.artifact_id)
        .then((q) => {
          if (cancelled) return;
          if (q.status === "generating") timer = setTimeout(load, POLL_MS);
          else setQuiz(q);
        })
        .catch((err) => {
          if (cancelled) return;
          // Missing is final. Anything else (the backend restarting) is
          // worth another look while the quiz may still be on its way.
          if (err instanceof StudyMissing) setError(err.message);
          else timer = setTimeout(load, POLL_MS);
        });
    };
    load();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [courseId, props.artifact_id]);

  const about = props.topic ? ` on ${props.topic}` : "";
  if (error) return <p className="qa-card qa-card-empty">{error}</p>;
  if (!quiz) {
    return (
      <div className="qa-card qa-card-pending" role="status">
        <span className="session-status-dot" aria-hidden="true"></span>
        Writing a practice quiz{about} from your course…
      </div>
    );
  }
  if (quiz.status === "error") {
    return (
      <p className="qa-card qa-card-empty">
        Couldn't write this quiz: {quiz.error ?? "something went wrong"} Ask again to try once more.
      </p>
    );
  }
  return (
    <div className="qa-card qa-card-quiz">
      <QuizView
        courseId={courseId}
        artifactId={quiz.id}
        initial={quiz}
        onExplain={onExplain}
        onOpenCitation={onOpenCitation}
        onOpenFull={() => onOpenStudy(quiz.id)}
      />
    </div>
  );
}
