/**
 * W2.5 / learning-loop A127+A132: hypercorrection feedback dwell.
 *
 * When the server returns `feedback_dwell_ms` (> 0) on a high-confidence wrong
 * grade, Continue / Next stays disabled until that many ms have elapsed so the
 * student attends to corrective feedback. Diagnosis only — never mastery weight.
 */
import { useLayoutEffect, useState } from "react";

/** True while a positive dwell window is still open (pure; clock injected). */
export function feedbackDwellLocked(dwellMs: number | null | undefined, startedAt: number, now: number): boolean {
  if (dwellMs == null || dwellMs <= 0) return false;
  return now - startedAt < dwellMs;
}

/**
 * One grade's dwell, as a fresh object: a second confident miss with the same
 * duration is a NEW arm (identity differs), so the hold runs again — a bare
 * number would compare equal and leave Continue enabled.
 */
export type DwellArm = { ms: number } | null;

/** The arm for a graded response's `feedback_dwell_ms` (null = no hold). */
export function dwellArm(ms: number | null | undefined): DwellArm {
  return ms != null && ms > 0 ? { ms } : null;
}

/**
 * Holds Continue / Next for the dwell after the value changes to a positive
 * duration (a new confident-wrong grade). Zero / null / undefined unlocks at
 * once. Pass a `dwellArm` to re-arm on every grade, equal durations included.
 */
export function useHypercorrectionDwell(arm: DwellArm | number | null | undefined): boolean {
  const ms = typeof arm === "number" ? arm : arm?.ms ?? null;
  const [locked, setLocked] = useState(() => (ms ?? 0) > 0);
  // A new value re-arms (or clears) the hold during render, the way React
  // adjusts state to a changed prop; the effect only owns the timer. A layout
  // effect, so the clock starts in the commit that first shows the hold.
  const [armedFor, setArmedFor] = useState(arm);
  if (!Object.is(armedFor, arm)) {
    setArmedFor(arm);
    setLocked(ms != null && ms > 0);
  }
  useLayoutEffect(() => {
    if (ms == null || ms <= 0) return;
    const id = window.setTimeout(() => setLocked(false), ms);
    return () => window.clearTimeout(id);
    // `arm`, not `ms`: an equal duration from a new grade restarts the timer.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [arm]);
  return locked;
}

export const HYPERCORRECTION_DWELL_COPY =
  "Take a moment with the feedback — you were sure about this one.";
