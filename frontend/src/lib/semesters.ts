import type { EnrolledCourse, Semester } from "@/lib/api";

// Bucket for enrollments whose offering has no term joined (the backend
// sends `term: ""`). These are never archived — an undatable course is
// shown with the current term rather than hidden behind the archive.
export const UNKNOWN_TERM_LABEL = "Other";

export type TermGroup = {
  label: string;
  courses: EnrolledCourse[];
};

// Mirrors the `sort_key` formula in migration 0019: year * 10 + term ordinal.
const TERM_ORDINALS: Record<string, number> = {
  spring: 1,
  summer: 2,
  fall: 3,
  winter: 4,
};

/**
 * Derive a `sort_key`-equivalent rank from a term label ("Fall 2025" -> 20253).
 *
 * Only used when `/api/semesters` gave us nothing to key on; when a real
 * semester row exists its `sort_key` always wins. Returns null when the label
 * carries no year, since there is then no defensible ordering for it.
 */
export function termRankFromLabel(label: string): number | null {
  const year = label.match(/\b(\d{4})\b/);
  if (!year) return null;
  const term = label.toLowerCase().match(/\b(spring|summer|fall|winter)\b/);
  return Number(year[1]) * 10 + (term ? TERM_ORDINALS[term[1]] : 0);
}

// Local calendar date as YYYY-MM-DD. Not toISOString(), which converts to UTC
// and lands on the wrong day either side of midnight.
function toISODate(today: Date | string): string {
  if (typeof today === "string") return today.slice(0, 10);
  const month = String(today.getMonth() + 1).padStart(2, "0");
  const day = String(today.getDate()).padStart(2, "0");
  return `${today.getFullYear()}-${month}-${day}`;
}

/**
 * The term `today` falls in, mirroring `services/academics.py::current_term`:
 * the highest-`sort_key` term whose [start_date, end_date] contains today,
 * falling back to the highest `sort_key` overall when today sits in a gap.
 *
 * Both rules must stay identical to the backend's or the two disagree about
 * which semester is "current". Date bounds are compared as YYYY-MM-DD strings,
 * where lexicographic order is chronological order.
 */
export function currentTerm(
  semesters: Semester[] | null | undefined,
  today: Date | string = new Date(),
): Semester | null {
  if (!semesters || semesters.length === 0) return null;
  const d = toISODate(today);
  const byRank = [...semesters].sort((a, b) => (b.sort_key ?? 0) - (a.sort_key ?? 0));
  const containing = byRank.find(
    (s) =>
      s.start_date &&
      s.end_date &&
      s.start_date.slice(0, 10) <= d &&
      s.end_date.slice(0, 10) >= d,
  );
  return containing ?? byRank[0];
}
