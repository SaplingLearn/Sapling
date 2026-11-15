// Pure display/parse helpers for GradePredictorPanel's AssignmentSliderRow.
import type { GradedAssignment } from "@/lib/types";

export interface HypotheticalScore {
  earned: number;
  possible: number;
  curveClassMean: number | null;  // overrides stored assignment class stats
  curveClassSd: number | null;
}

export interface SliderRowValues {
  /** The assignment carries a stored positive total. */
  hasSetTotal: boolean;
  /** A total exists to show: stored, or a truthy hypothetical one. */
  hasTotal: boolean;
  possible: number;
  earned: number;
  sliderMax: number;
  curveClassMean: number | null;
  curveClassSd: number | null;
}

export function hasStoredTotal(assignment: GradedAssignment): boolean {
  return assignment.points_possible !== null && (assignment.points_possible as number) > 0;
}

/** Predictor override takes priority (even an explicit null); falls back to the stored class stat. */
export function resolveCurveStat(
  override: number | null | undefined,
  stored: number | null | undefined,
): number | null {
  return override !== undefined ? override : (stored ?? null);
}

export function resolveSliderRow(
  assignment: GradedAssignment,
  hyp: HypotheticalScore | null,
): SliderRowValues {
  const hasSetTotal = hasStoredTotal(assignment);
  const possible = hyp?.possible ?? (hasSetTotal ? (assignment.points_possible as number) : 100);
  const earned = hyp?.earned ?? Math.round(possible / 2);
  return {
    hasSetTotal,
    hasTotal: hasSetTotal || !!hyp?.possible,
    possible,
    earned,
    sliderMax: possible > 0 ? possible : 100,
    curveClassMean: resolveCurveStat(hyp?.curveClassMean, assignment.curve_class_mean),
    curveClassSd: resolveCurveStat(hyp?.curveClassSd, assignment.curve_class_sd),
  };
}

/** `Number(s)` when finite, else null. Note `Number("")` is 0, so "" parses to 0. */
export function parseFinite(s: string): number | null {
  const n = Number(s);
  return Number.isFinite(n) ? n : null;
}

export function clampEarned(val: number, possible: number): number {
  return Math.max(0, Math.min(val, possible));
}

/** "Due MM/DD/YYYY" off an ISO date, or "No Due Date". */
export function formatDueDisplay(dueDate: string | null): string {
  return dueDate
    ? `Due ${dueDate.slice(5, 7)}/${dueDate.slice(8, 10)}/${dueDate.slice(0, 4)}`
    : "No Due Date";
}

/** The suffix after the category name in the row meta line. */
export function dueSuffix(dueDate: string | null): string {
  return dueDate ? ` · ${formatDueDisplay(dueDate)}` : "";
}

/** A 0–1 fraction as a whole-number percent string, or `fallback` when absent. */
export function fractionToPercentText(v: number | null | undefined, fallback: string): string {
  return v != null ? (v * 100).toFixed(0) : fallback;
}

/**
 * A class-stat percent input's value as the fraction to emit:
 * "" → null (clear the override), finite → value / 100, anything else →
 * undefined (ignore the keystroke).
 */
export function parseCurvePercent(s: string): number | null | undefined {
  if (s === "") return null;
  const v = parseFinite(s);
  return v !== null ? v / 100 : undefined;
}
