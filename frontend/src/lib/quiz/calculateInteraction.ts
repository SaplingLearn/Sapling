/**
 * W7.2 Calculate (design kit 7.13) — value + unit (+ optional steps) ↔ answerText.
 *
 * Encode: `value|unit` or `value|unit|steps`. Server grades value|unit only
 * (services/quiz/kit_grade.py).
 */

import type { CalculateInteraction, WireQuestion } from "./types";

const SEP = "|";

function cleanText(raw: unknown): string {
  if (typeof raw !== "string") return "";
  return raw.trim();
}

/** A usable Calculate payload: kind only; placeholders optional. */
export function asCalculateInteraction(
  raw: WireQuestion["interaction"] | null | undefined,
): CalculateInteraction | null {
  if (!raw || raw.kind !== "calculate") return null;
  const placeholder = cleanText(raw.placeholder) || undefined;
  const unitLabel = cleanText(raw.unitLabel) || undefined;
  const stepsPlaceholder = cleanText(raw.stepsPlaceholder) || undefined;
  return {
    kind: "calculate",
    ...(placeholder ? { placeholder } : {}),
    ...(unitLabel ? { unitLabel } : {}),
    ...(stepsPlaceholder ? { stepsPlaceholder } : {}),
  };
}

export interface CalculateAnswer {
  value: string;
  unit: string;
  steps: string;
}

/** True when both value and unit are non-empty (steps optional). */
export function isCalculateComplete(raw: string | null | undefined): boolean {
  const { value, unit } = decodeCalculateAnswer(raw);
  return Boolean(value && unit);
}

export function encodeCalculateAnswer(value: string, unit: string, steps = ""): string {
  const v = value.trim();
  const u = unit.trim();
  const s = steps.trim();
  if (!v && !u && !s) return "";
  if (!s) return `${v}${SEP}${u}`;
  return `${v}${SEP}${u}${SEP}${s}`;
}

export function decodeCalculateAnswer(raw: string | null | undefined): CalculateAnswer {
  const text = (raw ?? "").trim();
  if (!text) return { value: "", unit: "", steps: "" };
  const parts = text.split(SEP);
  return {
    value: (parts[0] ?? "").trim(),
    unit: (parts[1] ?? "").trim(),
    steps: parts.slice(2).join(SEP).trim(),
  };
}
