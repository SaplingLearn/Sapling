/**
 * W7 meta-row chips: Returning + exam-distance pips.
 *
 * Formula: docs/learning-loop/w7-meta-chips.md. Display only — never mastery.
 */

export type ExamDistancePips = 1 | 2 | 3 | 4 | 5;

/** True when the student has studied this concept before. */
export function isReturningConcept(
  timesStudied: number | null | undefined,
  lastStudiedAt: string | null | undefined,
): boolean {
  const times = typeof timesStudied === "number" && Number.isFinite(timesStudied)
    ? Math.max(0, Math.floor(timesStudied))
    : 0;
  if (times >= 1) return true;
  return Boolean(lastStudiedAt && String(lastStudiedAt).trim());
}

/**
 * Exam-distance (1 = nearest exam-ready … 5 = farthest).
 * Prefer tier; use mastery score only to split `learning`.
 */
export function examDistancePips(
  tier: string | null | undefined,
  mastery: number | null | undefined,
): ExamDistancePips {
  const t = (tier ?? "").trim().toLowerCase();
  const score =
    typeof mastery === "number" && Number.isFinite(mastery)
      ? Math.min(1, Math.max(0, mastery))
      : 0;
  if (t === "mastered") return 1;
  if (t === "learning") return score >= 0.55 ? 2 : 3;
  if (t === "struggling") return 4;
  return 5;
}

/** How many of five pips are filled (nearer → more filled). */
export function examDistanceFilled(pips: ExamDistancePips): number {
  return 6 - pips;
}
