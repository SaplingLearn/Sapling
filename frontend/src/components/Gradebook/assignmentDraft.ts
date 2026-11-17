/**
 * Pure form logic behind AssignmentModal: seeding the draft from the edited
 * assignment, parsing the numeric inputs, and validation. Kept JSX-free so
 * every edge case (blank vs 0, percent ↔ fraction, impossible dates) is unit
 * tested without rendering the dialog.
 */
import type { GradedAssignment } from "@/lib/types";
import type { AssignmentDraft } from "./AssignmentModal";

/** The four bell-curve fields, all cleared ("Remove curve"). */
export const CLEARED_CURVE = {
  curve_class_mean: null,
  curve_class_sd: null,
  curve_avg_target: null,
  curve_sd_delta: null,
} satisfies Partial<AssignmentDraft>;

/** An empty draft: what "New Assignment" starts from. */
export function emptyDraft(): AssignmentDraft {
  return {
    title: "",
    category_id: null,
    points_possible: null,
    points_earned: null,
    due_date: null,
    assignment_type: null,
    notes: null,
    ...CLEARED_CURVE,
  };
}

/**
 * The editable fields of `initial`, or an empty draft when creating. `??`
 * (not `||`) so a stored 0 or "" survives; only null/undefined fall back.
 */
export function draftFromAssignment(initial?: GradedAssignment | null): AssignmentDraft {
  if (!initial) return emptyDraft();
  return {
    title: initial.title ?? "",
    category_id: initial.category_id ?? null,
    points_possible: initial.points_possible ?? null,
    points_earned: initial.points_earned ?? null,
    due_date: initial.due_date ?? null,
    assignment_type: initial.assignment_type ?? null,
    notes: initial.notes ?? null,
    curve_class_mean: initial.curve_class_mean ?? null,
    curve_class_sd: initial.curve_class_sd ?? null,
    curve_avg_target: initial.curve_avg_target ?? null,
    curve_sd_delta: initial.curve_sd_delta ?? null,
  };
}

/** A points input: blank → null, anything else → Number (0 stays 0). */
export function parsePoints(value: string): number | null {
  return value === "" ? null : Number(value);
}

/** A percent input stored as a fraction: blank → null, "68" → 0.68. */
export function parsePercent(value: string): number | null {
  return value === "" ? null : Number(value) / 100;
}

/** A stored fraction shown as a one-decimal percent: 0.68 → "68.0", null → "". */
export function formatPercent(fraction: number | null): string {
  return fraction !== null ? (fraction * 100).toFixed(1) : "";
}

/** True when a due date is set but is not a real calendar day (e.g. 2026-02-30). */
export function isDueDateInvalid(dueDate: string | null): boolean {
  if (!dueDate) return false;
  const d = new Date(dueDate + "T00:00:00");
  return isNaN(d.getTime()) || dueDate !== d.toISOString().slice(0, 10);
}

/** Save is allowed with a non-blank title, a positive (or blank) total and a valid date. */
export function isDraftValid(draft: AssignmentDraft, dueDateInvalid: boolean): boolean {
  return draft.title.trim() !== "" &&
    (draft.points_possible === null || draft.points_possible > 0) &&
    !dueDateInvalid;
}

/** The "Remove curve" link shows once a class mean or SD is entered. */
export function hasCurveStats(draft: AssignmentDraft): boolean {
  return draft.curve_class_mean !== null || draft.curve_class_sd !== null;
}
