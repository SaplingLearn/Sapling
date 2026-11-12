"use client";
import React from "react";

import { Icon } from "@/components/Icon";
import type { WorkedExampleBlock } from "@/lib/studyGuide/types";

import { BlockFrame } from "./BlockFrame";
import s from "./blocks.module.css";

/** A problem solved one revealed step at a time. */
export function WorkedExampleBlockView({ block }: { block: WorkedExampleBlock }) {
  const total = block.steps.length;
  const [revealed, setRevealed] = React.useState(0);
  // A regenerated example can be shorter than the one it replaced.
  const shown = Math.min(revealed, total);
  return (
    <BlockFrame
      blockId={block.id}
      tone="amber"
      icon={<Icon name="bulb" size={15} />}
      label="Worked example"
      title={block.title}
      actions={
        <span className={s.counter}>
          {shown} of {total} steps
        </span>
      }
    >
      <div className={s.body}>
        <p className={s.problem}>{block.problem}</p>
        <ol className={s.steps}>
          {/* Steps not shown yet stay in the page, so a printout has them all. */}
          {block.steps.map((step, i) => (
            <li key={i} className={s.step} hidden={i >= shown}>
              <span className={s.stepNumber}>{i + 1}</span>
              <div className={s.stack}>
                <strong>{step.title}</strong>
                <span className={s.math}>{step.math}</span>
                <span className={s.dim}>{step.why}</span>
              </div>
            </li>
          ))}
        </ol>
        <div className={s.stepActions}>
          {shown < total && (
            <button
              type="button"
              className="btn btn--primary"
              data-testid={`guide-step-next-${block.id}`}
              onClick={() => setRevealed(shown + 1)}
            >
              {shown === 0 ? "Show first step" : "Show next step"}
            </button>
          )}
          {shown > 0 && (
            <button type="button" className="btn" data-testid={`guide-step-reset-${block.id}`} onClick={() => setRevealed(0)}>
              Start over
            </button>
          )}
        </div>
      </div>
    </BlockFrame>
  );
}
