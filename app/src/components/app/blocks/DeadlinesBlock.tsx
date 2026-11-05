import { countdownPercent, dueParts, formatDue, statusText } from "../../../assignmentStatus";
import type { AssignmentSummary, CanvasAssignment, DeadlinesProps } from "../../../sidecar";

// The rows and their order are what the backend picked when the student
// asked. Each row's status comes from the live assignments list when the app
// has it, so a saved chat doesn't say "not submitted" after it was turned in.
// A row the live list doesn't have (still loading, or gone from Canvas) shows
// as it was, can't be opened, and the card says when that was.
export default function DeadlinesBlock({
  props,
  live,
  onOpenAssignment,
}: {
  props: DeadlinesProps;
  live: CanvasAssignment[];
  onOpenAssignment: (id: number) => void;
}) {
  const byId = new Map(live.map((a) => [a.id, a]));
  const rows = props.assignments.map((saved) => ({ a: (byId.get(saved.id) ?? saved) as AssignmentSummary, known: byId.has(saved.id) }));
  const anyStale = rows.some((r) => !r.known);
  const countdownId = rows.find((r) => countdownPercent(r.a) !== null)?.a.id;

  return (
    <section className="qa-card" aria-label="Deadlines">
      <div className="qa-card-head">
        <span>Due in the next {props.days} {props.days === 1 ? "day" : "days"}</span>
        <span className="from">{anyStale ? `From Canvas, as of ${formatDue(props.as_of)}` : "From Canvas"}</span>
      </div>
      {rows.length === 0 ? (
        <p className="qa-card-empty">Nothing due in the next {props.days} {props.days === 1 ? "day" : "days"}.</p>
      ) : (
        rows.map(({ a, known }) => {
          const status = statusText(a);
          const when = dueParts(a.due_at);
          const percent = a.id === countdownId ? countdownPercent(a) : null;
          const inner = (
            <>
              <span className="when">
                <span className="day">{when.day}</span>
                <span className="dow">{when.dow}</span>
              </span>
              <span className="body">
                <span className="ttl">{a.name}</span>
                <span className={`status ${status.tone}`}>{status.text}</span>
                {percent !== null && (
                  <span className="count" aria-hidden="true">
                    <i style={{ width: `${percent}%` }}></i>
                  </span>
                )}
              </span>
            </>
          );
          return known ? (
            <button className="assign-row" key={a.id} type="button" onClick={() => onOpenAssignment(a.id)}>
              {inner}
            </button>
          ) : (
            <div className="assign-row stale" key={a.id}>
              {inner}
            </div>
          );
        })
      )}
    </section>
  );
}
