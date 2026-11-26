/**
 * W7.2 Build (design kit ~7.x construct) — placement ↔ `answerText` for a
 * short_answer wire.
 *
 * DISPLAY + SESSION STATE ONLY. Generation does not emit `interaction` yet;
 * grading still uses the short-answer path on whatever string Check sends.
 * Encode is stable so a fixture key can match, and decode restores the tray
 * when the student pages back to an unanswered draft.
 *
 * Design kit: target slots + a Parts tray. This seam is click-to-assign only —
 * ordered or unordered assembly into a structure. Prefer `kind: "build"` even
 * if a design frame names it "construct".
 */

import type { BuildInteraction, BuildInteractionPart, BuildInteractionSlot, WireQuestion } from "./types";

/** part id → slot index, or null while still in the tray. */
export type BuildAssignment = Record<string, number | null>;

const SEP_SLOT = ";";
const SEP_NAME = "=";

function safeId(raw: unknown): string {
  if (typeof raw !== "string") return "";
  const id = raw.trim();
  if (!id || id.includes(SEP_SLOT) || id.includes(SEP_NAME)) return "";
  return id;
}

function cleanSlots(raw: BuildInteractionSlot[] | undefined): BuildInteractionSlot[] {
  const seen = new Set<string>();
  const slots: BuildInteractionSlot[] = [];
  for (const s of raw ?? []) {
    const id = safeId(s?.id);
    const label = typeof s?.label === "string" ? s.label.trim() : "";
    if (!id || !label || seen.has(id)) continue;
    seen.add(id);
    slots.push({ id, label });
  }
  return slots;
}

function cleanParts(raw: BuildInteractionPart[] | undefined): BuildInteractionPart[] {
  const seen = new Set<string>();
  const parts: BuildInteractionPart[] = [];
  for (const it of raw ?? []) {
    const id = safeId(it?.id);
    const label = typeof it?.label === "string" ? it.label.trim() : "";
    if (!id || !label || seen.has(id)) continue;
    seen.add(id);
    parts.push({ id, label });
  }
  return parts;
}

/**
 * A usable Build payload: ≥1 slot, parts ≥ slots (equal counts like Label, or
 * extras in the tray), unique non-empty ids with no slot/part id collision.
 */
export function asBuildInteraction(
  raw: WireQuestion["interaction"] | null | undefined,
): BuildInteraction | null {
  if (!raw || raw.kind !== "build") return null;
  const slots = cleanSlots(raw.slots);
  const parts = cleanParts(raw.parts);
  if (slots.length === 0 || parts.length === 0) return null;
  if (parts.length < slots.length) return null;
  const slotIds = new Set(slots.map(s => s.id));
  if (parts.some(p => slotIds.has(p.id))) return null;
  return { kind: "build", slots, parts };
}

/** Empty tray assignment for every part. */
export function emptyBuildAssignment(parts: BuildInteractionPart[]): BuildAssignment {
  return Object.fromEntries(parts.map(it => [it.id, null]));
}

/** True when every slot holds a part (extras may remain in the tray). */
export function isBuildComplete(interaction: BuildInteraction, assign: BuildAssignment): boolean {
  return interaction.slots.every((_, slotIndex) =>
    interaction.parts.some(it => assign[it.id] === slotIndex),
  );
}

/**
 * `head=phosphate;sugar=deoxyribose;base=adenine` — slot order is the
 * interaction's; empty slots keep a trailing `=`.
 */
export function encodeBuildAnswer(interaction: BuildInteraction, assign: BuildAssignment): string {
  return interaction.slots
    .map((slot, slotIndex) => {
      const placed = interaction.parts.find(it => assign[it.id] === slotIndex);
      return `${slot.id}${SEP_NAME}${placed?.id ?? ""}`;
    })
    .join(SEP_SLOT);
}

/** Restore placements from `answerText`; unknown ids / slots are ignored. */
export function decodeBuildAnswer(
  interaction: BuildInteraction,
  raw: string | null | undefined,
): BuildAssignment {
  const assign = emptyBuildAssignment(interaction.parts);
  const text = (raw ?? "").trim();
  if (!text) return assign;
  const byPart = new Map(interaction.parts.map(it => [it.id, it]));
  const bySlot = new Map(interaction.slots.map((s, i) => [s.id, i]));
  const taken = new Set<number>();
  for (const part of text.split(SEP_SLOT)) {
    const eq = part.indexOf(SEP_NAME);
    if (eq <= 0) continue;
    const slot = bySlot.get(part.slice(0, eq));
    if (slot == null || taken.has(slot)) continue;
    const partId = part.slice(eq + 1);
    if (!partId || !byPart.has(partId) || assign[partId] != null) continue;
    assign[partId] = slot;
    taken.add(slot);
  }
  return assign;
}

/**
 * Place `partId` on `slot` (or return it to the tray when `slot` is null).
 * Occupying a filled slot returns that slot's previous part to the tray.
 */
export function placeBuildItem(
  assign: BuildAssignment,
  partId: string,
  slot: number | null,
): BuildAssignment {
  if (!(partId in assign)) return assign;
  const next: BuildAssignment = { ...assign, [partId]: slot };
  if (typeof slot === "number") {
    for (const [id, at] of Object.entries(assign)) {
      if (id !== partId && at === slot) next[id] = null;
    }
  }
  return next;
}
