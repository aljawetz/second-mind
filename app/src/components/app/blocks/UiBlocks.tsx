import { Fragment } from "react";
import type { CanvasAssignment, UiBlock } from "../../../sidecar";
import DeadlinesBlock from "./DeadlinesBlock";

export interface BlockContext {
  assignments: CanvasAssignment[];
  onOpenAssignment: (id: number) => void;
}

// The cards an answer can carry, by component name. Only names listed here
// render; anything else the backend sends (a newer card, a bad line) shows
// nothing rather than breaking the answer.
function renderBlock(block: UiBlock, ctx: BlockContext) {
  switch (block.component) {
    case "deadlines":
      return <DeadlinesBlock props={block.props} live={ctx.assignments} onOpenAssignment={ctx.onOpenAssignment} />;
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
