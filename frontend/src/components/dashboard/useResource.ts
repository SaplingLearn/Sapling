"use client";
import { useCallback, useEffect, useState } from "react";

/**
 * One Dashboard resource (graph, courses, sessions, assignments, notes) with
 * its OWN truthful state, so one region failing never blanks another
 * (docs/07 §7).
 *
 *   loading    — first fetch for this key, nothing to show yet
 *   ready      — data for this key
 *   refreshing — a retry is in flight; the last data for this key stays up
 *   stale      — a retry failed; the last data for this key stays up, flagged
 *   error      — the fetch failed and there is nothing valid to show
 *   idle       — no key (not signed in yet, or the resource is switched off)
 *
 * `key` names WHAT is being fetched (user + scope). A response for an older
 * key is dropped by the effect cleanup, so a late answer for the previous
 * semester can never paint over the current one; data from another key is
 * never shown as this key's (a scope change shows `loading`, not old data).
 * `fetcher` must be memoised on the same inputs as `key`.
 */
export type ResourceStatus = "idle" | "loading" | "ready" | "refreshing" | "stale" | "error";

export interface Resource<T> {
  status: ResourceStatus;
  data: T | null;
  retry: () => void;
}

type Settled<T> = { key: string; attempt: number; ok: boolean; data: T | null };

export function useResource<T>(key: string | null, fetcher: () => Promise<T>): Resource<T> {
  const [attempt, setAttempt] = useState(0);
  const [settled, setSettled] = useState<Settled<T> | null>(null);

  useEffect(() => {
    if (!key) return;
    let cancelled = false;
    fetcher().then(
      (data) => {
        if (!cancelled) setSettled({ key, attempt, ok: true, data });
      },
      () => {
        if (cancelled) return;
        setSettled((prev) => ({
          key,
          attempt,
          ok: false,
          // keep this key's last good data (stale), never another key's
          data: prev && prev.key === key ? prev.data : null,
        }));
      },
    );
    return () => {
      cancelled = true;
    };
  }, [key, attempt, fetcher]);

  const retry = useCallback(() => setAttempt((a) => a + 1), []);

  if (!key) return { status: "idle", data: null, retry };
  const current = settled && settled.key === key ? settled : null;
  if (!current) return { status: "loading", data: null, retry };
  if (current.attempt !== attempt) {
    return { status: current.data != null ? "refreshing" : "loading", data: current.data, retry };
  }
  if (current.ok) return { status: "ready", data: current.data, retry };
  return { status: current.data != null ? "stale" : "error", data: current.data, retry };
}

/** True once the resource has something trustworthy to render. */
export const hasData = (s: ResourceStatus) => s === "ready" || s === "refreshing" || s === "stale";
