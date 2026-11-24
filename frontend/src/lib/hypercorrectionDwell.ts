/**
 * W2.5 / learning-loop A127+A132: hypercorrection feedback dwell.
 *
 * When the server returns `feedback_dwell_ms` (> 0) on a high-confidence wrong
 * grade, Continue / Next stays disabled until that many ms have elapsed so the
 * student attends to corrective feedback. Diagnosis only — never mastery weight.
 */
import { useEffect, useState } from "react";

/** True while a positive dwell window is still open (pure; clock injected). */
export function feedbackDwellLocked(dwellMs: number | null | undefined, startedAt: number, now: number): boolean {
  if (dwellMs == null || dwellMs <= 0) return false;
  return now - startedAt < dwellMs;
}

/**
 * Holds Continue / Next for `dwellMs` after the value changes to a positive
 * duration (a new confident-wrong grade). Zero / null / undefined unlocks at once.
 */
export function useHypercorrectionDwell(dwellMs: number | null | undefined): boolean {
  const [locked, setLocked] = useState(() => (dwellMs ?? 0) > 0);
  useEffect(() => {
    if (dwellMs == null || dwellMs <= 0) {
      setLocked(false);
      return;
    }
    setLocked(true);
    const started = Date.now();
    const id = window.setTimeout(() => setLocked(false), Math.max(0, dwellMs - (Date.now() - started)));
    return () => window.clearTimeout(id);
  }, [dwellMs]);
  return locked;
}

export const HYPERCORRECTION_DWELL_COPY =
  "Take a moment with the feedback — you were sure about this one.";
