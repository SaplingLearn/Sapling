"use client";
import React from "react";

/**
 * ProgressDots — where you are in a fixed-length sequence (#537).
 *
 * The column variant is the design's "branch": a hairline rail with a dot per
 * question — filled for answered, a hollow accent ring for the current one,
 * a smaller hollow dot for what's ahead. Onboarding has the same grammar
 * inline and horizontal (`Onboarding.tsx`), which is what `orientation="row"`
 * is for; this is the shared version.
 *
 * Read-only, it is one `role="img"` with a spoken label ("Question 3 of 5")
 * rather than a list of nine anonymous dots: the dots are a picture of the
 * label, and reading them out individually tells a screen-reader user nothing.
 *
 * With `onSelect` it becomes navigation: each dot is a numbered button (the
 * quiz's question pager) in a `role="group"` that keeps the same label, and
 * the current one carries `aria-current="step"`.
 */
export interface ProgressDotsProps {
  total: number;
  /** 0-based index of the item being worked on. */
  current: number;
  /** How many items are answered — contiguous from 0. Ignored when `done`
   *  is given. */
  answered: number;
  /** Per item: answered or not — for a sequence answered out of order, where
   *  "answered" is not a prefix. */
  done?: ReadonlyArray<boolean>;
  orientation?: "column" | "row";
  /** Per dot: true = answered correctly, false = incorrectly, null/absent =
   *  not marked (or the verdict is being held back). Colours the dot. */
  outcomes?: ReadonlyArray<boolean | null>;
  /** Makes each dot a numbered button that jumps to its item. */
  onSelect?: (index: number) => void;
  /** With `onSelect`: the buttons show but can't be pressed right now. */
  disabled?: boolean;
  ariaLabel: string;
  testid?: string;
}

export function ProgressDots({
  total,
  current,
  answered,
  done,
  orientation = "column",
  outcomes,
  onSelect,
  disabled = false,
  ariaLabel,
  testid,
}: ProgressDotsProps) {
  const interactive = onSelect !== undefined;
  return (
    <div
      className={`progress-dots progress-dots--${orientation}${interactive ? " progress-dots--steps" : ""}`}
      role={interactive ? "group" : "img"}
      aria-label={ariaLabel}
      data-testid={testid}
    >
      {Array.from({ length: Math.max(0, total) }, (_, i) => {
        // Current wins over answered: revisiting an answered item still shows
        // "you are here", which is the question the rail exists to answer.
        const isDone = done ? done[i] === true : i < answered;
        const kind = i === current ? "current" : isDone ? "done" : "todo";
        const outcome = outcomes?.[i];
        const marked = outcome == null ? undefined : outcome ? "correct" : "incorrect";
        const className = `progress-dots__dot progress-dots__dot--${kind}`;
        if (!onSelect) {
          return <span key={i} className={className} data-outcome={marked} />;
        }
        return (
          <button
            key={i}
            type="button"
            className={`${className} progress-dots__dot--step`}
            data-outcome={marked}
            aria-label={`Question ${i + 1}, ${marked ?? (isDone ? "answered" : "not answered")}`}
            aria-current={i === current ? "step" : undefined}
            disabled={disabled}
            onClick={() => onSelect(i)}
          >
            {i + 1}
          </button>
        );
      })}
    </div>
  );
}
