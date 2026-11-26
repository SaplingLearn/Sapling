/**
 * W7.2 Sort (kit 7.1) — placement ↔ `answerText` for a short_answer wire.
 *
 * DISPLAY + SESSION STATE ONLY. Wire may carry `interaction` when generation
 * attaches it (docs/learning-loop/w7-generation-emit.md); prompt emit later.
 * Grading still uses the short-answer path on whatever string Check sends.
 * Encode is stable so a fixture key can match, and decode restores the tray
 * when the student pages back to an unanswered draft.
 */

import type { SortInteraction, SortInteractionItem, WireQuestion } from "./types";

/** item id → bucket index, or null while still in the tray. */
export type SortAssignment = Record<string, number | null>;

const SEP_BUCKET = ";";
const SEP_ITEM = ",";
const SEP_NAME = "=";

/** A usable Sort payload: ≥2 buckets, ≥1 item, unique non-empty ids. */
export function asSortInteraction(
  raw: WireQuestion["interaction"] | null | undefined,
): SortInteraction | null {
  if (!raw || raw.kind !== "sort") return null;
  const buckets = (raw.buckets ?? []).map(b => b.trim()).filter(Boolean);
  if (buckets.length < 2) return null;
  const seen = new Set<string>();
  const items: SortInteractionItem[] = [];
  for (const it of raw.items ?? []) {
    const id = typeof it?.id === "string" ? it.id.trim() : "";
    const label = typeof it?.label === "string" ? it.label.trim() : "";
    if (!id || !label || seen.has(id)) continue;
    if (id.includes(SEP_BUCKET) || id.includes(SEP_NAME) || id.includes(SEP_ITEM)) continue;
    seen.add(id);
    items.push({ id, label });
  }
  if (items.length === 0) return null;
  return { kind: "sort", buckets, items };
}

/** Empty tray assignment for every item. */
export function emptyAssignment(items: SortInteractionItem[]): SortAssignment {
  return Object.fromEntries(items.map(it => [it.id, null]));
}

/** True when every item sits in a real bucket. */
export function isSortComplete(interaction: SortInteraction, assign: SortAssignment): boolean {
  return interaction.items.every(it => {
    const bucket = assign[it.id];
    return typeof bucket === "number" && bucket >= 0 && bucket < interaction.buckets.length;
  });
}

/**
 * `Prokaryote=e-coli,streptococcus;Eukaryote=yeast,amoeba` — bucket order is
 * the interaction's; items within a bucket keep interaction order.
 */
export function encodeSortAnswer(interaction: SortInteraction, assign: SortAssignment): string {
  return interaction.buckets
    .map((name, bucket) => {
      const ids = interaction.items
        .filter(it => assign[it.id] === bucket)
        .map(it => it.id);
      return `${name}${SEP_NAME}${ids.join(SEP_ITEM)}`;
    })
    .join(SEP_BUCKET);
}

/** Restore placements from `answerText`; unknown ids / buckets are ignored. */
export function decodeSortAnswer(
  interaction: SortInteraction,
  raw: string | null | undefined,
): SortAssignment {
  const assign = emptyAssignment(interaction.items);
  const text = (raw ?? "").trim();
  if (!text) return assign;
  const byId = new Map(interaction.items.map(it => [it.id, it]));
  const byBucket = new Map(interaction.buckets.map((name, i) => [name, i]));
  for (const part of text.split(SEP_BUCKET)) {
    const eq = part.indexOf(SEP_NAME);
    if (eq <= 0) continue;
    const bucket = byBucket.get(part.slice(0, eq));
    if (bucket == null) continue;
    for (const id of part.slice(eq + 1).split(SEP_ITEM)) {
      if (!id || !byId.has(id)) continue;
      assign[id] = bucket;
    }
  }
  return assign;
}

/** Place `itemId` in `bucket` (or return it to the tray when `bucket` is null). */
export function placeSortItem(
  assign: SortAssignment,
  itemId: string,
  bucket: number | null,
): SortAssignment {
  if (!(itemId in assign)) return assign;
  return { ...assign, [itemId]: bucket };
}
