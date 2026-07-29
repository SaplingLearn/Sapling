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

function read(): string {
  if (typeof window === "undefined") return "";
  return window.localStorage.getItem(ACTIVE_SEMESTER_STORAGE_KEY) ?? "";
}

/** [activeSemester, setActiveSemester, hydrated] — persisted to localStorage, cross-tab + same-tab
 *  reactive. `hydrated` is false until the localStorage read completes after mount.
 *
 *  Semantics: the EMPTY string is the default and means "All semesters" —
 *  every surface fetches/filters unscoped. Scoping is strictly opt-in: it
 *  applies only once the user picks a term in the Courses & Semesters hub
 *  (which stores the term label here); the hub's "All semesters" tab clears it
 *  back to "". Nothing auto-resolves a default term — an auto-picked term
 *  silently hides cross-term data (vetoed by the e2e lane, see #360). */
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
