"use client";
import { useEffect, useState } from "react";

import { getLoopStatus } from "@/lib/api";

/** How long Learn waits for the loop probe before rendering the legacy tree †. */
export const LOOP_STATUS_TIMEOUT_MS = 2_500;
/** Back-off after a FAILED probe (not a slow one) †; bounded, then legacy stays. */
export const LOOP_STATUS_RETRY_MS: readonly number[] = [2_000, 5_000, 15_000];

/** Learning loop (PKG-13): which Learn tree to render. null = unresolved,
 *  false = the legacy tree, true = LoopLearn. Reads nothing but the loop status
 *  probe — never `learning_loop_beta`, which no settings field carries (spec
 *  §7, §13 A31).
 *
 *  Never blocks, never strands (PKG-13 fix round): no answer within
 *  LOOP_STATUS_TIMEOUT_MS, or a failed probe, renders legacy PROVISIONALLY
 *  (build phase: fail closed; a failed probe is retried on LOOP_STATUS_RETRY_MS);
 *  a definitive {active: true} — however late — switches to the loop, because
 *  the backend delegates the legacy routes to the loop for that student
 *  (routes/learn.py `_loop_delegate`) and the legacy screen would misbehave on
 *  them. A definitive {active: false} is final. */
export function useLoopStatus(userId: string, userReady: boolean): boolean | null {
  // Keyed on the user the answer is for, so a user switch reads as unresolved
  // until its own probe answers (no setState in the effect body).
  const [resolved, setResolved] = useState<{ userId: string; active: boolean; final: boolean } | null>(null);
  useEffect(() => {
    if (!userReady || !userId) return;
    let cancelled = false;
    let retryTimer: ReturnType<typeof setTimeout> | undefined;
    const provisional = () => {
      if (cancelled) return;
      setResolved((prev) => (prev?.userId === userId && prev.final ? prev : { userId, active: false, final: false }));
    };
    const timeout = setTimeout(provisional, LOOP_STATUS_TIMEOUT_MS);
    const probe = (attempt: number) => {
      getLoopStatus(userId)
        .then((r) => {
          if (cancelled) return;
          clearTimeout(timeout);
          setResolved({ userId, active: Boolean(r.active), final: true });
        })
        .catch(() => {
          if (cancelled) return;
          clearTimeout(timeout);
          provisional();
          const delay = LOOP_STATUS_RETRY_MS[attempt];
          if (delay !== undefined) retryTimer = setTimeout(() => probe(attempt + 1), delay);
        });
    };
    probe(0);
    return () => {
      cancelled = true;
      clearTimeout(timeout);
      if (retryTimer !== undefined) clearTimeout(retryTimer);
    };
  }, [userId, userReady]);
  if (!userReady) return null;
  if (!userId) return false;
  return resolved?.userId === userId ? resolved.active : null;
}
