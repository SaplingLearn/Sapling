"use client";

import { useCallback, useEffect, useState } from "react";

export const ACTIVE_SEMESTER_STORAGE_KEY = "sapling_active_semester";
const CHANGE_EVENT = "sapling-active-semester-change";

/** Distinct term labels in first-seen order, dropping blanks. */
export function distinctTerms(courses: { term: string }[]): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const c of courses) {
    if (c.term && !seen.has(c.term)) {
      seen.add(c.term);
      out.push(c.term);
    }
  }
  return out;
}

/**
 * The semester to actually scope by: the stored `active` value when it is one
 * of the user's enrolled terms, else the most-recently-enrolled term. Courses
 * arrive `enrolled_at` ascending, so the last distinct term is the most recent.
 * (Heuristic default; can be upgraded to term `sort_key` ordering later.)
 */
export function resolveActiveSemester(active: string, courses: { term: string }[]): string {
  const terms = distinctTerms(courses);
  if (active && terms.includes(active)) return active;
  return terms.length ? terms[terms.length - 1] : "";
}

function read(): string {
  if (typeof window === "undefined") return "";
  return window.localStorage.getItem(ACTIVE_SEMESTER_STORAGE_KEY) ?? "";
}

/**
 * Persist a default active semester when none is stored yet. Screens that read
 * `useActiveSemester` but don't run the Dashboard's default resolution call
 * this at the point where they already have the user's term labels (most
 * recent first, e.g. `courseTermLabels(courses)`). No-op when a value is
 * already stored or no label is available. Writes through the same
 * change-event path as the hook's setter, so every mounted `useActiveSemester`
 * updates and scoped fetches re-run scoped.
 */
export function ensureDefaultActiveSemester(termLabels: string[]): void {
  if (typeof window === "undefined") return;
  if (read()) return;
  const def = termLabels.find((t) => !!t);
  if (!def) return;
  window.localStorage.setItem(ACTIVE_SEMESTER_STORAGE_KEY, def);
  window.dispatchEvent(new Event(CHANGE_EVENT));
}

/** [activeSemester, setActiveSemester, hydrated] — persisted to localStorage, cross-tab + same-tab
 *  reactive. `hydrated` is false until the localStorage read completes after mount. */
export function useActiveSemester(): [string, (v: string) => void, boolean] {
  const [sem, setSem] = useState<string>("");
  // `hydrated` flips true once we've read localStorage after mount. We start at
  // "" (not the stored value) to avoid an SSR/CSR hydration mismatch, so callers
  // that fetch based on the active semester should wait for `hydrated` to avoid
  // an initial unscoped fetch followed by a scoped refetch.
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    setSem(read());
    setHydrated(true);
    const onStorage = (e: StorageEvent) => {
      if (e.key === ACTIVE_SEMESTER_STORAGE_KEY) setSem(read());
    };
    const onCustom = () => setSem(read());
    window.addEventListener("storage", onStorage);
    window.addEventListener(CHANGE_EVENT, onCustom);
    return () => {
      window.removeEventListener("storage", onStorage);
      window.removeEventListener(CHANGE_EVENT, onCustom);
    };
  }, []);

  // Stable identity so consumers can safely list it in effect/callback deps.
  const update = useCallback((v: string) => {
    if (typeof window === "undefined") return;
    window.localStorage.setItem(ACTIVE_SEMESTER_STORAGE_KEY, v);
    setSem(v);
    window.dispatchEvent(new Event(CHANGE_EVENT));
  }, []);

  return [sem, update, hydrated];
}
