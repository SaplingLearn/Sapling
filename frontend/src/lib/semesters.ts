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
