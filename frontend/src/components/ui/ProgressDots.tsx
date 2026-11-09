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
 * One `role="img"` with a spoken label ("Question 3 of 5") rather than a list
 * of nine anonymous dots: the dots are a picture of the label, and reading
 * them out individually tells a screen-reader user nothing.
 */
export interface ProgressDotsProps {
  total: number;
  /** 0-based index of the item being worked on. */
  current: number;
  /** How many items are answered — contiguous from 0. */
  answered: number;
  orientation?: "column" | "row";
  /** Per dot: true = answered correctly, false = incorrectly, null/absent =
   *  not marked (or the verdict is being held back). Colours the dot. */
  outcomes?: ReadonlyArray<boolean | null>;
  ariaLabel: string;
  testid?: string;
}

export function ProgressDots({
  total,
  current,
  answered,
  orientation = "column",
  outcomes,
  ariaLabel,
  testid,
}: ProgressDotsProps) {
  return (
    <div
      className={`progress-dots progress-dots--${orientation}`}
      role="img"
      aria-label={ariaLabel}
      data-testid={testid}
    >
      {Array.from({ length: Math.max(0, total) }, (_, i) => {
        // Current wins over answered: revisiting an answered item still shows
        // "you are here", which is the question the rail exists to answer.
        const kind = i === current ? "current" : i < answered ? "done" : "todo";
        const outcome = outcomes?.[i];
        return (
          <span
            key={i}
            className={`progress-dots__dot progress-dots__dot--${kind}`}
            data-outcome={outcome == null ? undefined : outcome ? "correct" : "incorrect"}
          />
        );
      })}
    </div>
  );
}
