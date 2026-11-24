/**
 * W7.2 Sequence (kit 7.2) — order ↔ `answerText` for a short_answer wire.
 *
 * DISPLAY + SESSION STATE ONLY. Generation does not emit `interaction` yet;
 * grading still uses the short-answer path on whatever string Check sends.
 * Encode is stable so a fixture key can match, and decode restores the tray
 * when the student pages back to an unanswered draft.
 *
 * Click-to-assign: select a tray card, then a numbered slot (1…n). Tap a
 * placed card to return it to the tray.
 */

import type { SequenceInteraction, SequenceInteractionStep, WireQuestion } from "./types";

/** step id → slot index, or null while still in the tray. */
export type SequenceAssignment = Record<string, number | null>;

const SEP = ";";

function safeId(raw: unknown): string {
  if (typeof raw !== "string") return "";
  const id = raw.trim();
  if (!id || id.includes(SEP)) return "";
  return id;
}

function cleanSteps(raw: SequenceInteractionStep[] | undefined): SequenceInteractionStep[] {
  const seen = new Set<string>();
  const steps: SequenceInteractionStep[] = [];
  for (const s of raw ?? []) {
    const id = safeId(s?.id);
    const label = typeof s?.label === "string" ? s.label.trim() : "";
    if (!id || !label || seen.has(id)) continue;
    seen.add(id);
    steps.push({ id, label });
  }
  return steps;
}

/** A usable Sequence payload: ≥2 steps, unique non-empty ids. */
export function asSequenceInteraction(
  raw: WireQuestion["interaction"] | null | undefined,
): SequenceInteraction | null {
  if (!raw || raw.kind !== "sequence") return null;
  const steps = cleanSteps(raw.steps);
  if (steps.length < 2) return null;
  return { kind: "sequence", steps };
}

/** Empty tray assignment for every step. */
export function emptySequenceAssignment(steps: SequenceInteractionStep[]): SequenceAssignment {
  return Object.fromEntries(steps.map(it => [it.id, null]));
}

/** True when every step sits in a real slot (and thus every slot is filled). */
export function isSequenceComplete(
  interaction: SequenceInteraction,
  assign: SequenceAssignment,
): boolean {
  return interaction.steps.every(it => {
    const slot = assign[it.id];
    return typeof slot === "number" && slot >= 0 && slot < interaction.steps.length;
  });
}

/**
 * `prophase;metaphase;anaphase;telophase` — slot order; empty slots keep a
 * bare gap (trailing empties preserved so length matches step count).
 */
export function encodeSequenceAnswer(
  interaction: SequenceInteraction,
  assign: SequenceAssignment,
): string {
  return interaction.steps
    .map((_, slot) => interaction.steps.find(it => assign[it.id] === slot)?.id ?? "")
    .join(SEP);
}

/** Restore placements from `answerText`; unknown ids / overflow are ignored. */
export function decodeSequenceAnswer(
  interaction: SequenceInteraction,
  raw: string | null | undefined,
): SequenceAssignment {
  const assign = emptySequenceAssignment(interaction.steps);
  const parts = (raw ?? "").split(SEP);
  const byId = new Set(interaction.steps.map(s => s.id));
  const n = interaction.steps.length;
  for (let slot = 0; slot < n; slot++) {
    const id = (parts[slot] ?? "").trim();
    if (!id || !byId.has(id)) continue;
    // First mention wins if a duplicate id appears.
    if (assign[id] != null) continue;
    assign[id] = slot;
  }
  return assign;
}

/**
 * Place `stepId` in `slot` (or return it to the tray when `slot` is null).
 * Occupying a filled slot sends the previous step back to the tray.
 */
export function placeSequenceItem(
  assign: SequenceAssignment,
  stepId: string,
  slot: number | null,
): SequenceAssignment {
  if (!(stepId in assign)) return assign;
  const next: SequenceAssignment = { ...assign, [stepId]: slot };
  if (slot == null) return next;
  for (const [id, at] of Object.entries(next)) {
    if (id !== stepId && at === slot) next[id] = null;
  }
  return next;
}
