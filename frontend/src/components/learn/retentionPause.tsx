/**
 * What the retention check (RetentionCheck.tsx) says when /posttest/start or
 * /posttest/answer is refused (#866 K13).
 *
 * The loop's A20 rate limit answers both with the 429 "ai budget reached" and
 * a `reset_at`: a pause with a reset time, shown as the banner DueQueue shows
 * above this card, never the raw sentinel. A 5xx carries the server's internal
 * detail ("grader unavailable", "post-test unavailable; retry"): nothing was
 * recorded, so the card says that in its own words.
 */
import React from "react";

import type { LoopBudgetPause } from "@/lib/api";
import { extractErrorDetail, humanizeError } from "@/lib/errorMessage";
import { BudgetPausedBanner, formatResetAt } from "./BudgetPausedBanner";

export function retentionPauseMessage(pause: LoopBudgetPause): string {
  return pause.resetAt
    ? `AI checks are paused until ${formatResetAt(pause.resetAt)}. Nothing was recorded; try again then.`
    : "AI checks are paused for now. Nothing was recorded; try again later.";
}

/** `fallback` (or the server's own readable words) for an ordinary failure;
 *  `unavailable` for a 5xx, whose detail is not for the student. */
export function retentionErrorText(err: unknown, fallback: string, unavailable: string): string {
  return (extractErrorDetail(err).status ?? 0) >= 500 ? unavailable : humanizeError(err, fallback);
}

/** The pause banner (`retention-budget-paused`), or nothing. Focusable, so the
 *  action that met the pause can move focus to it (spec §13 A135). */
export function RetentionPauseBanner({ pause, focusRef }: {
  pause: LoopBudgetPause | null;
  focusRef: React.Ref<HTMLDivElement>;
}) {
  if (!pause) return null;
  return (
    <div ref={focusRef} tabIndex={-1}>
      <BudgetPausedBanner
        testId="retention-budget-paused"
        resetAt={pause.resetAt}
        sessionCapped={pause.sessionCapped}
        message={retentionPauseMessage(pause)}
      />
    </div>
  );
}
