/**
 * W7.2 Explain (design kit 7.16) — multi-line prose ↔ `answerText` for a
 * short_answer wire.
 *
 * DISPLAY + SESSION STATE ONLY. Generation does not emit `interaction` yet;
 * grading still uses the short-answer path on whatever string Check sends.
 * Rubric lines are informational (shown after Check); per-criterion marks and
 * mic input stay deferred.
 */

import type { ExplainInteraction, WireQuestion } from "./types";

function cleanText(raw: unknown): string {
  if (typeof raw !== "string") return "";
  return raw.trim();
}

function cleanRubric(raw: string[] | undefined): string[] {
  const out: string[] = [];
  const seen = new Set<string>();
  for (const row of raw ?? []) {
    const text = cleanText(row);
    if (!text || seen.has(text)) continue;
    seen.add(text);
    out.push(text);
    if (out.length >= 8) break;
  }
  return out;
}

/**
 * A usable Explain payload: kind only is enough; placeholder/rubric optional.
 */
export function asExplainInteraction(
  raw: WireQuestion["interaction"] | null | undefined,
): ExplainInteraction | null {
  if (!raw || raw.kind !== "explain") return null;
  const placeholder = cleanText(raw.placeholder) || undefined;
  const rubric = cleanRubric(raw.rubric);
  return {
    kind: "explain",
    ...(placeholder ? { placeholder } : {}),
    ...(rubric.length ? { rubric } : {}),
  };
}

/** True when the student has typed a non-empty explanation. */
export function isExplainComplete(raw: string | null | undefined): boolean {
  return Boolean((raw ?? "").trim());
}

/** Identity encode — the wire is the prose itself. */
export function encodeExplainAnswer(text: string | null | undefined): string {
  return (text ?? "").trim();
}

/** Identity decode. */
export function decodeExplainAnswer(raw: string | null | undefined): string {
  return (raw ?? "").trim();
}
