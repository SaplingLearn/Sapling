import { compareTermLabels } from "@/lib/semesters";
import type { GpaCourseRow } from "@/lib/types";

export interface TranscriptSemester {
  label: string;
  gpa: number | null;
  courses: GpaCourseRow[];
}

/**
 * The credits a row actually weighs: null/zero/negative count as 1, so a
 * course always weighs at least once. Mirrors the falsy-credits default in
 * backend/services/gradebook_service.py::weighted_gpa. The ONE place this
 * rule lives — both the GPA math and the transcript's "N cr" display use it,
 * so the number shown is always the number weighed.
 */
export function effectiveCredits(row: Pick<GpaCourseRow, "credits">): number {
  return row.credits != null && row.credits > 0 ? row.credits : 1;
}

/**
 * Credit-weighted GPA over a set of course rows.
 *
 * Mirrors backend/services/gradebook_service.py::weighted_gpa and must stay
 * in lock-step with it: rows with `grade_points == null` (in-progress) are
 * skipped entirely; credits default via `effectiveCredits` above; nothing
 * contributing → null, never 0.0.
 */
export function weightedGpa(rows: GpaCourseRow[]): number | null {
  let totalCredits = 0;
  let totalPoints = 0;
  for (const row of rows) {
    if (row.grade_points == null) continue;
    const credits = effectiveCredits(row);
    totalCredits += credits;
    totalPoints += row.grade_points * credits;
  }
  if (totalCredits === 0) return null;
  return totalPoints / totalCredits;
}

/**
 * Group `/api/gradebook/gpa` rows into per-semester transcript sections,
 * most recent term first (ordering via lib/semesters, the one place term
 * order is defined). In-progress rows stay listed in their section but are
 * excluded from that section's GPA by `weightedGpa` above.
 */
export function buildTranscript(rows: GpaCourseRow[]): TranscriptSemester[] {
  const groups = new Map<string, GpaCourseRow[]>();
  for (const row of rows) {
    const label = (row.semester || "").trim();
    const group = groups.get(label);
    if (group) group.push(row);
    else groups.set(label, [row]);
  }
  return Array.from(groups.entries())
    .sort(([a], [b]) => compareTermLabels(a, b))
    .map(([label, courses]) => ({
      label,
      gpa: weightedGpa(courses),
      courses,
    }));
}
