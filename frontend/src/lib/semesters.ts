import type { EnrolledCourse, Semester } from "@/lib/api";

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
 * The current term. The SERVER decides it (#766): pass `serverCurrentId` —
 * `GET /api/semesters`' `current_term_id` — and that row wins, because the
 * browser's clock and timezone can disagree with the backend's on a boundary
 * day, and the backend is what enrolls and resolves offerings.
 *
 * Without it (the fetch failed, an older backend, or a frozen test-mode clock
 * that must stay authoritative for determinism) this falls back to mirroring
 * `services/academics.py::current_term` against `today`: the
 * highest-`sort_key` term whose [start_date, end_date] contains today; in a
 * gap, the most recently STARTED term (never a future one seeded ahead of
 * time); before every term, the soonest. Date bounds are compared as
 * YYYY-MM-DD strings, where lexicographic order is chronological order.
 */
export function currentTerm(
  semesters: Semester[] | null | undefined,
  today: Date | string = new Date(),
  serverCurrentId?: string | null,
): Semester | null {
  if (!semesters || semesters.length === 0) return null;
  if (serverCurrentId) {
    const fromServer = semesters.find((s) => s.id === serverCurrentId);
    if (fromServer) return fromServer;
  }
  const d = toISODate(today);
  const start = (s: Semester) => (s.start_date || "").slice(0, 10);
  const byRank = [...semesters].sort((a, b) => (b.sort_key ?? 0) - (a.sort_key ?? 0));
  const containing = byRank.find(
    (s) =>
      s.start_date &&
      s.end_date &&
      start(s) <= d &&
      s.end_date.slice(0, 10) >= d,
  );
  if (containing) return containing;
  const dated = byRank.filter((s) => start(s));
  const started = dated
    .filter((s) => start(s) <= d)
    .sort((a, b) => start(b).localeCompare(start(a)));
  if (started.length) return started[0];
  const upcoming = [...dated].sort(
    (a, b) => start(a).localeCompare(start(b)) || (a.sort_key ?? 0) - (b.sort_key ?? 0),
  );
  return upcoming[0] ?? byRank[0];
}

function rankIndex(semesters: Semester[] | null | undefined): Map<string, number> {
  const index = new Map<string, number>();
  for (const s of semesters ?? []) {
    if (s.label) index.set(s.label, s.sort_key ?? 0);
  }
  return index;
}

function labelRank(label: string, index: Map<string, number>): number | null {
  const known = index.get(label);
  return known !== undefined ? known : termRankFromLabel(label);
}

// Most recent first; labels we can't rank at all sort to the end.
function compareLabels(a: string, b: string, index: Map<string, number>): number {
  const ra = labelRank(a, index);
  const rb = labelRank(b, index);
  if (ra !== null && rb !== null) return rb - ra || a.localeCompare(b);
  if (ra !== null) return -1;
  if (rb !== null) return 1;
  return a.localeCompare(b);
}

const NO_SEMESTER_INDEX: Map<string, number> = new Map();

/**
 * Most-recent-first comparator for bare term labels, for callers that have no
 * `/api/semesters` rows to key on (e.g. the transcript's per-semester groups).
 * Label-derived ranks only; unrankable labels sort to the end.
 */
export function compareTermLabels(a: string, b: string): number {
  return compareLabels(a, b, NO_SEMESTER_INDEX);
}

/**
 * Distinct term labels off a course list, most recent first — the semester
 * chips on the gradebook landing. Courses with no term contribute nothing;
 * a chip for them would filter to an empty gradebook.
 */
export function courseTermLabels(
  courses: EnrolledCourse[] | null | undefined,
  semesters?: Semester[] | null,
): string[] {
  const index = rankIndex(semesters);
  const labels = new Set<string>();
  for (const course of courses ?? []) {
    const label = (course.term || "").trim();
    if (label) labels.add(label);
  }
  return Array.from(labels).sort((a, b) => compareLabels(a, b, index));
}
