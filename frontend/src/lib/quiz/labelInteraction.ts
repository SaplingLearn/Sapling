/**
 * W7.2 Label (kit 7.4) — placement ↔ `answerText` for a short_answer wire.
 *
 * DISPLAY + SESSION STATE ONLY. Generation does not emit `interaction` yet;
 * grading still uses the short-answer path on whatever string Check sends.
 * Encode is stable so a fixture key can match, and decode restores the tray
 * when the student pages back to an unanswered draft.
 *
 * Design kit: numbered spots + a Labels tray (drag in the DC). This seam is
 * click-to-assign only — no SVG diagram paths yet.
 */

import type { LabelInteraction, LabelInteractionItem, LabelInteractionSpot, WireQuestion } from "./types";

/** label id → spot index, or null while still in the tray. */
export type LabelAssignment = Record<string, number | null>;

const SEP_SPOT = ";";
const SEP_NAME = "=";

function safeId(raw: unknown): string {
  if (typeof raw !== "string") return "";
  const id = raw.trim();
  if (!id || id.includes(SEP_SPOT) || id.includes(SEP_NAME)) return "";
  return id;
}

function cleanSpots(raw: LabelInteractionSpot[] | undefined): LabelInteractionSpot[] {
  const seen = new Set<string>();
  const spots: LabelInteractionSpot[] = [];
  for (const s of raw ?? []) {
    const id = safeId(s?.id);
    const label = typeof s?.label === "string" ? s.label.trim() : "";
    if (!id || !label || seen.has(id)) continue;
    seen.add(id);
    spots.push({ id, label });
  }
  return spots;
}

function cleanLabels(raw: LabelInteractionItem[] | undefined): LabelInteractionItem[] {
  const seen = new Set<string>();
  const labels: LabelInteractionItem[] = [];
  for (const it of raw ?? []) {
    const id = safeId(it?.id);
    const label = typeof it?.label === "string" ? it.label.trim() : "";
    if (!id || !label || seen.has(id)) continue;
    seen.add(id);
    labels.push({ id, label });
  }
  return labels;
}

/** A usable Label payload: ≥1 spot, matching label count, unique non-empty ids. */
export function asLabelInteraction(
  raw: WireQuestion["interaction"] | null | undefined,
): LabelInteraction | null {
  if (!raw || raw.kind !== "label") return null;
  const spots = cleanSpots(raw.spots);
  const labels = cleanLabels(raw.labels);
  if (spots.length === 0 || labels.length === 0) return null;
  // One label per spot (design kit 7.4). Unequal counts are not a usable stub.
  if (spots.length !== labels.length) return null;
  const spotIds = new Set(spots.map(s => s.id));
  if (labels.some(l => spotIds.has(l.id))) return null;
  return { kind: "label", spots, labels };
}

/** Empty tray assignment for every label. */
export function emptyLabelAssignment(labels: LabelInteractionItem[]): LabelAssignment {
  return Object.fromEntries(labels.map(it => [it.id, null]));
}

/** True when every label sits on a real spot (and thus every spot is filled). */
export function isLabelComplete(interaction: LabelInteraction, assign: LabelAssignment): boolean {
  return interaction.labels.every(it => {
    const spot = assign[it.id];
    return typeof spot === "number" && spot >= 0 && spot < interaction.spots.length;
  });
}

/**
 * `aorta=aorta;pa=pulmonary;ra=right-atrium;lv=left-ventricle` — spot order is
 * the interaction's; empty spots keep a trailing `=`.
 */
export function encodeLabelAnswer(interaction: LabelInteraction, assign: LabelAssignment): string {
  return interaction.spots
    .map((spot, spotIndex) => {
      const placed = interaction.labels.find(it => assign[it.id] === spotIndex);
      return `${spot.id}${SEP_NAME}${placed?.id ?? ""}`;
    })
    .join(SEP_SPOT);
}

/** Restore placements from `answerText`; unknown ids / spots are ignored. */
export function decodeLabelAnswer(
  interaction: LabelInteraction,
  raw: string | null | undefined,
): LabelAssignment {
  const assign = emptyLabelAssignment(interaction.labels);
  const text = (raw ?? "").trim();
  if (!text) return assign;
  const byLabel = new Map(interaction.labels.map(it => [it.id, it]));
  const bySpot = new Map(interaction.spots.map((s, i) => [s.id, i]));
  const taken = new Set<number>();
  for (const part of text.split(SEP_SPOT)) {
    const eq = part.indexOf(SEP_NAME);
    if (eq <= 0) continue;
    const spot = bySpot.get(part.slice(0, eq));
    if (spot == null || taken.has(spot)) continue;
    const labelId = part.slice(eq + 1);
    if (!labelId || !byLabel.has(labelId) || assign[labelId] != null) continue;
    assign[labelId] = spot;
    taken.add(spot);
  }
  return assign;
}

/**
 * Place `labelId` on `spot` (or return it to the tray when `spot` is null).
 * Occupying a filled spot returns that spot's previous label to the tray.
 */
export function placeLabelItem(
  assign: LabelAssignment,
  labelId: string,
  spot: number | null,
): LabelAssignment {
  if (!(labelId in assign)) return assign;
  const next: LabelAssignment = { ...assign, [labelId]: spot };
  if (typeof spot === "number") {
    for (const [id, at] of Object.entries(assign)) {
      if (id !== labelId && at === spot) next[id] = null;
    }
  }
  return next;
}
