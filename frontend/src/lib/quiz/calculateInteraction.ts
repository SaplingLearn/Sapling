/**
 * W7.2 Calculate (design kit 7.13) — value + unit ↔ `answerText` for a
 * short_answer wire.
 *
 * DISPLAY + SESSION STATE ONLY. Generation does not emit `interaction` yet;
 * grading still uses the short-answer path. Working-steps UI is deferred.
 * Encode is `value|unit` (pipe) so a fixture key can match.
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
  return {
    kind: "calculate",
    ...(placeholder ? { placeholder } : {}),
    ...(unitLabel ? { unitLabel } : {}),
  };
}

export interface CalculateAnswer {
  value: string;
  unit: string;
}

/** True when both value and unit are non-empty. */
export function isCalculateComplete(raw: string | null | undefined): boolean {
  const { value, unit } = decodeCalculateAnswer(raw);
  return Boolean(value && unit);
}

export function encodeCalculateAnswer(value: string, unit: string): string {
  const v = value.trim();
  const u = unit.trim();
  if (!v && !u) return "";
  return `${v}${SEP}${u}`;
}

export function decodeCalculateAnswer(raw: string | null | undefined): CalculateAnswer {
  const text = (raw ?? "").trim();
  if (!text) return { value: "", unit: "" };
  const pipe = text.indexOf(SEP);
  if (pipe < 0) return { value: text, unit: "" };
  return {
    value: text.slice(0, pipe).trim(),
    unit: text.slice(pipe + 1).trim(),
  };
}
