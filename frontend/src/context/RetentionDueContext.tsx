"use client";
import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

import { useFlag } from "@/context/FlagsContext";
import { useUser } from "@/context/UserContext";
import { fetchRetentionDue } from "@/lib/api";

/** Spec §13 A126: the "retention check due" badge (Study nav entry, Dashboard)
 *  is behind this client-visible flag. Off — the default — fetches nothing. */
export const RETENTION_DUE_FLAG = "retention_due_badge";
/** How often an open, visible tab asks again. The server caches each student's
 *  answer for POSTTEST_DUE_CACHE_S (300 s) and clears it when they open or
 *  answer a retention check, so asking more often buys nothing. */
export const RETENTION_DUE_REFRESH_MS = 5 * 60_000;

export interface RetentionDueState {
  due: boolean;
  /** Courses with a retention check to take now, for the Study deep link. */
  courseIds: string[];
  /** Ask again now — after the student opened or answered a check. */
  refresh: () => void;
}

const NOTHING_DUE: Omit<RetentionDueState, "refresh"> = { due: false, courseIds: [] };
const RetentionDueContext = createContext<RetentionDueState>({ ...NOTHING_DUE, refresh: () => {} });

/**
 * ONE cheap read for the whole shell — never a request per nav render or per
 * page: on sign-in (flag on), then every RETENTION_DUE_REFRESH_MS on a visible
 * tab, and on `refresh()`. A failed read hides the badge (it never claims a
 * check is due that the server could not vouch for). It never opens a
 * retention check: only the student's own click does that.
 */
export function RetentionDueProvider({ children }: { children: React.ReactNode }) {
  const { userId, isAuthenticated } = useUser();
  const enabled = useFlag(RETENTION_DUE_FLAG) === "on" && isAuthenticated && !!userId;
  const [answer, setAnswer] = useState<{ who: string; due: boolean; courseIds: string[] } | null>(null);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    // Inside an async callback, so no setter runs synchronously in the effect.
    void (async () => {
      try {
        const res = await fetchRetentionDue(userId);
        if (!cancelled) setAnswer({ who: userId, due: !!res.due, courseIds: res.course_ids ?? [] });
      } catch {
        if (!cancelled) setAnswer({ who: userId, ...NOTHING_DUE });
      }
    })();
    return () => { cancelled = true; };
  }, [enabled, userId, tick]);

  useEffect(() => {
    if (!enabled) return;
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") setTick((t) => t + 1);
    }, RETENTION_DUE_REFRESH_MS);
    return () => window.clearInterval(timer);
  }, [enabled]);

  const refresh = useCallback(() => setTick((t) => t + 1), []);
  const value = useMemo<RetentionDueState>(() => {
    const mine = enabled && answer !== null && answer.who === userId ? answer : NOTHING_DUE;
    return { due: mine.due, courseIds: mine.courseIds, refresh };
  }, [enabled, answer, userId, refresh]);
  return <RetentionDueContext.Provider value={value}>{children}</RetentionDueContext.Provider>;
}

/** The shell's retention-due state; nothing due outside the provider. */
export function useRetentionDue(): RetentionDueState {
  return useContext(RetentionDueContext);
}

/** The Study deep link that opens the retention check for the first due course. */
export function retentionHref(courseIds: string[]): string {
  return courseIds[0] ? `/study?${new URLSearchParams({ "retention-course": courseIds[0] })}` : "/study";
}
