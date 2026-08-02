"use client";

import { useCallback, useEffect, useState } from "react";

export const ACTIVE_SEMESTER_STORAGE_KEY = "sapling_active_semester";
const CHANGE_EVENT = "sapling-active-semester-change";

type TermScoped = { term?: string | null; terms?: string[] | null };

/** Every term label a course/concept belongs to. Prefers the `terms` array (a
 *  course collapsed across enrollments carries all its terms, #449); falls back
 *  to the singular `term` for older payloads. */
function termsOf(c: TermScoped): string[] {
  if (c.terms && c.terms.length) return c.terms;
  return c.term ? [c.term] : [];
}

/** True if the course/concept belongs to `activeSemester`. The empty string
 *  ("All semesters") always matches. Uses term MEMBERSHIP, so a course enrolled
 *  in both Fall 2025 and Spring 2026 shows on either tab (not just its
 *  most-recent representative term). */
export function courseInTerm(c: TermScoped, activeSemester: string): boolean {
  if (!activeSemester) return true;
  return termsOf(c).includes(activeSemester);
}

/** Distinct term labels in first-seen order, dropping blanks. Flattens the
 *  per-course `terms` array so every enrolled term surfaces as a tab. */
export function distinctTerms(courses: TermScoped[]): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const c of courses) {
    for (const t of termsOf(c)) {
      if (t && !seen.has(t)) {
        seen.add(t);
        out.push(t);
      }
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
