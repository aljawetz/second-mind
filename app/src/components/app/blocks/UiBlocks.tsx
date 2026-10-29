import { Fragment } from "react";
import type { CanvasAssignment, Citation, UiBlock } from "../../../sidecar";
import DeadlinesBlock from "./DeadlinesBlock";
import QuizBlock from "./QuizBlock";

export interface BlockContext {
  courseId: number;
  assignments: CanvasAssignment[];
  onOpenAssignment: (id: number) => void;
  onOpenStudy: (id: string) => void;
  onExplain: (prompt: string) => void;
  onOpenCitation: (c: Citation) => void;
}

// The cards an answer can carry, by component name. Only names listed here
// render; anything else the backend sends (a newer card, a bad line) shows
// nothing rather than breaking the answer.
function renderBlock(block: UiBlock, ctx: BlockContext) {
  switch (block.component) {
    case "deadlines":
      return <DeadlinesBlock props={block.props} live={ctx.assignments} onOpenAssignment={ctx.onOpenAssignment} />;
    case "quiz":
      return (
        <QuizBlock
          props={block.props}
          courseId={ctx.courseId}
          onOpenStudy={ctx.onOpenStudy}
          onExplain={ctx.onExplain}
          onOpenCitation={ctx.onOpenCitation}
        />
      );
    default:
      return null;
  }
}

export default function UiBlocks({ blocks, ctx }: { blocks: UiBlock[]; ctx: BlockContext }) {
  if (blocks.length === 0) return null;
  return (
    <div className="qa-cards">
      {blocks.map((b) => (
        <Fragment key={b.id}>{renderBlock(b, ctx)}</Fragment>
      ))}
    </div>
  );
}
