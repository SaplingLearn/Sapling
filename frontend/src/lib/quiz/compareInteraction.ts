/**
 * W7.2 Compare — pick one relation between two sides ↔ `answerText` for a
 * short_answer wire.
 *
 * DISPLAY + SESSION STATE ONLY. Generation does not emit `interaction` yet;
 * grading still uses the short-answer path on whatever string Check sends.
 * Encode is the chosen option id so a fixture key can match.
 *
 * Design kit: two fixed panels (left / right) + relation chips (e.g. only
 * left, only right, both, neither). Click one option; click again to clear.
 */

import type {
  CompareInteraction,
  CompareInteractionOption,
  CompareInteractionSide,
  WireQuestion,
} from "./types";

function safeId(raw: unknown): string {
  if (typeof raw !== "string") return "";
  const id = raw.trim();
  if (!id || id.includes("=") || id.includes(";")) return "";
  return id;
}

function cleanSide(raw: CompareInteractionSide | undefined): CompareInteractionSide | null {
  if (!raw) return null;
  const id = safeId(raw.id);
  const label = typeof raw.label === "string" ? raw.label.trim() : "";
  if (!id || !label) return null;
  return { id, label };
}

function cleanOptions(raw: CompareInteractionOption[] | undefined): CompareInteractionOption[] {
  const seen = new Set<string>();
  const options: CompareInteractionOption[] = [];
  for (const it of raw ?? []) {
    const id = safeId(it?.id);
    const label = typeof it?.label === "string" ? it.label.trim() : "";
    if (!id || !label || seen.has(id)) continue;
    seen.add(id);
    options.push({ id, label });
  }
  return options;
}

/**
 * A usable Compare payload: two sides with distinct ids, ≥2 relation options,
 * no option id colliding with a side id.
 */
export function asCompareInteraction(
  raw: WireQuestion["interaction"] | null | undefined,
): CompareInteraction | null {
  if (!raw || raw.kind !== "compare") return null;
  const left = cleanSide(raw.left);
  const right = cleanSide(raw.right);
  const options = cleanOptions(raw.options);
  if (!left || !right || left.id === right.id || options.length < 2) return null;
  const sideIds = new Set([left.id, right.id]);
  if (options.some(o => sideIds.has(o.id))) return null;
  return { kind: "compare", left, right, options };
}

/** True when `answerText` names one of the relation options. */
export function isCompareComplete(
  interaction: CompareInteraction,
  raw: string | null | undefined,
): boolean {
  const id = decodeCompareAnswer(interaction, raw);
  return id != null;
}

/** Encode: the chosen option id (empty string while unanswered). */
export function encodeCompareAnswer(optionId: string | null | undefined): string {
  return (optionId ?? "").trim();
}

/**
 * Restore the chosen option id from `answerText`; unknown / empty → null.
 */
export function decodeCompareAnswer(
  interaction: CompareInteraction,
  raw: string | null | undefined,
): string | null {
  const id = (raw ?? "").trim();
  if (!id) return null;
  return interaction.options.some(o => o.id === id) ? id : null;
}
