/**
 * W7.2 Rank & Judge (design kit 7.15) — ordered ids + why ↔ `answerText`.
 *
 * DISPLAY + SESSION STATE ONLY. Generation does not emit `interaction` yet.
 * Encode: `id;id;…` + record separator + why prose.
 */

import type { RankInteraction, RankInteractionItem, WireQuestion } from "./types";

export type RankAssignment = Record<string, number | null>;

const SEP_ORDER = ";";
const SEP_WHY = "\u001e";

function safeId(raw: unknown): string {
  if (typeof raw !== "string") return "";
  const id = raw.trim();
  if (!id || id.includes(SEP_ORDER) || id.includes(SEP_WHY)) return "";
  return id;
}

function cleanItems(raw: RankInteractionItem[] | undefined): RankInteractionItem[] {
  const seen = new Set<string>();
  const items: RankInteractionItem[] = [];
  for (const it of raw ?? []) {
    const id = safeId(it?.id);
    const label = typeof it?.label === "string" ? it.label.trim() : "";
    if (!id || !label || seen.has(id)) continue;
    seen.add(id);
    items.push({ id, label });
  }
  return items;
}

/** ≥2 items. */
export function asRankInteraction(
  raw: WireQuestion["interaction"] | null | undefined,
): RankInteraction | null {
  if (!raw || raw.kind !== "rank") return null;
  const items = cleanItems(raw.items);
  if (items.length < 2) return null;
  const hint = typeof raw.hint === "string" && raw.hint.trim() ? raw.hint.trim() : undefined;
  const whyPlaceholder =
    typeof raw.whyPlaceholder === "string" && raw.whyPlaceholder.trim()
      ? raw.whyPlaceholder.trim()
      : undefined;
  return {
    kind: "rank",
    items,
    ...(hint ? { hint } : {}),
    ...(whyPlaceholder ? { whyPlaceholder } : {}),
  };
}

export function emptyRankAssignment(items: RankInteractionItem[]): RankAssignment {
  return Object.fromEntries(items.map(it => [it.id, null]));
}

export function isRankOrderComplete(
  interaction: RankInteraction,
  assign: RankAssignment,
): boolean {
  return interaction.items.every(it => {
    const slot = assign[it.id];
    return typeof slot === "number" && slot >= 0 && slot < interaction.items.length;
  });
}

export function isRankComplete(
  interaction: RankInteraction,
  raw: string | null | undefined,
): boolean {
  const { assign, why } = decodeRankAnswer(interaction, raw);
  return isRankOrderComplete(interaction, assign) && Boolean(why.trim());
}

export function encodeRankAnswer(
  interaction: RankInteraction,
  assign: RankAssignment,
  why: string,
): string {
  const order = interaction.items
    .map((_, slot) => interaction.items.find(it => assign[it.id] === slot)?.id ?? "")
    .join(SEP_ORDER);
  const prose = why.trim();
  return prose ? `${order}${SEP_WHY}${prose}` : order;
}

export function decodeRankAnswer(
  interaction: RankInteraction,
  raw: string | null | undefined,
): { assign: RankAssignment; why: string } {
  const assign = emptyRankAssignment(interaction.items);
  const text = raw ?? "";
  const sep = text.indexOf(SEP_WHY);
  const orderPart = (sep < 0 ? text : text.slice(0, sep)).trim();
  const why = sep < 0 ? "" : text.slice(sep + 1).trim();
  if (!orderPart) return { assign, why };
  const parts = orderPart.split(SEP_ORDER);
  const byId = new Set(interaction.items.map(i => i.id));
  const n = interaction.items.length;
  for (let slot = 0; slot < n; slot++) {
    const id = (parts[slot] ?? "").trim();
    if (!id || !byId.has(id) || assign[id] != null) continue;
    assign[id] = slot;
  }
  return { assign, why };
}

export function placeRankItem(
  assign: RankAssignment,
  itemId: string,
  slot: number | null,
): RankAssignment {
  if (!(itemId in assign)) return assign;
  const next: RankAssignment = { ...assign, [itemId]: slot };
  if (typeof slot === "number") {
    for (const [id, at] of Object.entries(assign)) {
      if (id !== itemId && at === slot) next[id] = null;
    }
  }
  return next;
}
