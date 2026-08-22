"use client";

/**
 * The XP/streak line on the results screen (R-9).
 *
 * `POST /api/quiz/submit` pays XP through `award_xp_safe` and bumps the streak
 * inside `apply_graph_update`, but returns neither (gap G8) — the response is
 * score/total/mastery only. The only way to show "+30 XP · 4-day streak" is to
 * read `GET /api/gamification/me` before the session and again after the submit
 * and subtract.
 *
 * Both reads are best-effort. If either fails the whole line is omitted rather
 * than showing a delta we'd have had to invent.
 */

import { useCallback, useRef, useState } from "react";
import { fetchGamificationMe } from "@/lib/api";
import type { GamificationMe } from "@/lib/types";
import type { QuizSession } from "./types";

export interface GamificationDelta {
  /** The pre-quiz snapshot, for anything that wants to render it live. */
  before: GamificationMe | null;
  /** Take the "before" reading. Call at session start; never throws. */
  snapshotBefore(): Promise<void>;
  /** Take the "after" reading. Call once the submit has landed; never throws. */
  readAfter(): Promise<{ xp: number; streak: number } | null>;
  /** The two composed into the session's `xp` field — `null` if either read
   *  failed, or if no snapshot was taken. */
  deltaAfterSubmit(): Promise<QuizSession["xp"]>;
}

export function useGamificationDelta(userId: string): GamificationDelta {
  const [before, setBefore] = useState<GamificationMe | null>(null);
  // The ref is what the async submit chain reads: a closure captured at render
  // time would still be holding the pre-snapshot `null`.
  const beforeRef = useRef<GamificationMe | null>(null);

  const snapshotBefore = useCallback(async () => {
    if (!userId) return;
    try {
      const me = await fetchGamificationMe(userId);
      beforeRef.current = me;
      setBefore(me);
    } catch {
      beforeRef.current = null;
      setBefore(null);
    }
  }, [userId]);

  const readAfter = useCallback(async () => {
    if (!userId) return null;
    try {
      const me = await fetchGamificationMe(userId);
      return { xp: me.total_xp, streak: me.streak };
    } catch {
      return null;
    }
  }, [userId]);

  const deltaAfterSubmit = useCallback(async () => {
    const start = beforeRef.current;
    const end = await readAfter();
    if (!start || !end) return null;
    return { before: start.total_xp, after: end.xp, streak: end.streak };
  }, [readAfter]);

  return { before, snapshotBefore, readAfter, deltaAfterSubmit };
}
