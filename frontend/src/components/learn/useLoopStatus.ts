"use client";
import { useEffect, useState } from "react";

import { getLoopStatus } from "@/lib/api";

/** Learning loop (PKG-13): which Learn tree to render. null = unresolved,
 *  false = the legacy tree, true = LoopLearn. Fails closed to legacy on any
 *  error (build phase; PKG-14b narrows that to 404 / {active: false}). Reads
 *  nothing but the loop status probe — never `learning_loop_beta`, which no
 *  settings field carries (spec §7, §13 A31). */
export function useLoopStatus(userId: string, userReady: boolean): boolean | null {
  // Keyed on the user the answer is for, so a user switch reads as unresolved
  // until its own probe answers (no setState in the effect body).
  const [resolved, setResolved] = useState<{ userId: string; active: boolean } | null>(null);
  useEffect(() => {
    if (!userReady || !userId) return;
    let cancelled = false;
    getLoopStatus(userId)
      .then((r) => { if (!cancelled) setResolved({ userId, active: Boolean(r.active) }); })
      .catch(() => { if (!cancelled) setResolved({ userId, active: false }); });
    return () => { cancelled = true; };
  }, [userId, userReady]);
  if (!userReady) return null;
  if (!userId) return false;
  return resolved?.userId === userId ? resolved.active : null;
}
