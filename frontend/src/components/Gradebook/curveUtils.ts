import type { GradedAssignment, GradebookCourse } from "@/lib/types";

/**
 * Apply a bell curve adjustment to a single score percentage (0–1).
 *
 * z_score      = (score_pct - class_mean) / class_sd
 * curved_grade = avg_target + z_score * sd_delta
 *
 * Returns score_pct unchanged when class_sd === 0 (prevents division by zero).
 * Result is clamped to [0, 1].
 */
export function applyCurve(
  scorePct: number,
  classMean: number,
  classSd: number,
  avgTarget: number,
  sdDelta: number,
): number {
  if (classSd <= 0) return scorePct;
  const z = (scorePct - classMean) / classSd;
  return Math.max(0, Math.min(1, avgTarget + z * sdDelta));
}

/**
 * Return a GradedAssignment with points_earned replaced by the curved value.
 * Returns the original assignment unchanged if it has no curve data.
 */
export function applyCurveToAssignment(
  a: GradedAssignment,
  coursePolicy: { curve_avg_target: number; curve_sd_delta: number },
): GradedAssignment {
  if (
    a.points_earned === null ||
    a.curve_class_mean == null ||
    a.curve_class_sd == null
  ) return a;
  const rawPct = a.points_earned / (a.points_possible ?? 1);
  const avgTarget = a.curve_avg_target ?? coursePolicy.curve_avg_target;
  const sdDelta = a.curve_sd_delta ?? coursePolicy.curve_sd_delta;
  const curved = applyCurve(rawPct, a.curve_class_mean, a.curve_class_sd, avgTarget, sdDelta);
  return { ...a, points_earned: curved * (a.points_possible ?? 1) };
}

/**
 * Apply a final-grade bell curve to a 0–100 percentage.
 * Returns pct unchanged if the course has no final curve configured.
 */
export function applyFinalCurve(
  pct: number,
  course: Pick<GradebookCourse, "curve_final_mean" | "curve_final_sd" | "curve_avg_target" | "curve_sd_delta">,
): number {
  if (
    course.curve_final_mean == null ||
    course.curve_final_sd == null ||
    course.curve_avg_target == null ||
    course.curve_sd_delta == null
  ) return pct;
  return applyCurve(
    pct / 100,
    course.curve_final_mean,
    course.curve_final_sd,
    course.curve_avg_target,
    course.curve_sd_delta,
  ) * 100;
}

/** Returns true when the assignment has enough data for a curve to be applied. */
export function hasCurveData(a: GradedAssignment): boolean {
  return a.curve_class_mean != null && a.curve_class_sd != null;
}
