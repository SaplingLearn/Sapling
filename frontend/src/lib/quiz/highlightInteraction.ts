/**
 * W7.2 Highlight (design kit 7.10) — selected passages ↔ `answerText` for a
 * short_answer wire.
 *
 * DISPLAY + SESSION STATE ONLY. Generation does not emit `interaction` yet;
 * grading still uses the short-answer path on whatever string Check sends.
 * Encode is a stable, sorted id list so a fixture key can match.
 */

import type { HighlightInteraction, HighlightInteractionPassage, WireQuestion } from "./types";

const SEP = ",";

function safeId(raw: unknown): string {
  if (typeof raw !== "string") return "";
  const id = raw.trim();
  if (!id || id.includes(SEP) || id.includes("=") || id.includes(";")) return "";
  return id;
}

function cleanPassages(raw: HighlightInteractionPassage[] | undefined): HighlightInteractionPassage[] {
  const seen = new Set<string>();
  const passages: HighlightInteractionPassage[] = [];
  for (const it of raw ?? []) {
    const id = safeId(it?.id);
    const label = typeof it?.label === "string" ? it.label.trim() : "";
    if (!id || !label || seen.has(id)) continue;
    seen.add(id);
    passages.push({ id, label });
  }
  return passages;
}

/**
 * A usable Highlight payload: ≥2 passages, minSelected in 1…passages.length.
 */
export function asHighlightInteraction(
  raw: WireQuestion["interaction"] | null | undefined,
): HighlightInteraction | null {
  if (!raw || raw.kind !== "highlight") return null;
  const passages = cleanPassages(raw.passages);
  if (passages.length < 2) return null;
  let minSelected = 1;
  if (typeof raw.minSelected === "number" && Number.isFinite(raw.minSelected)) {
    const n = Math.floor(raw.minSelected);
    if (n >= 1 && n <= passages.length) minSelected = n;
  }
  const note = typeof raw.note === "string" ? raw.note.trim() : "";
  return {
    kind: "highlight",
    passages,
    minSelected,
    ...(note ? { note } : {}),
  };
}

export function highlightMinSelected(interaction: HighlightInteraction): number {
  return interaction.minSelected ?? 1;
}

/** True when at least `minSelected` known passage ids are chosen. */
export function isHighlightComplete(
  interaction: HighlightInteraction,
  raw: string | null | undefined,
): boolean {
  return decodeHighlightAnswer(interaction, raw).length >= highlightMinSelected(interaction);
}

/** Encode selected ids sorted for a stable fixture key. */
export function encodeHighlightAnswer(selectedIds: string[]): string {
  return [...new Set(selectedIds.map(id => id.trim()).filter(Boolean))].sort().join(SEP);
}

/** Restore selected ids; unknown ids dropped; order follows interaction. */
export function decodeHighlightAnswer(
  interaction: HighlightInteraction,
  raw: string | null | undefined,
): string[] {
  const text = (raw ?? "").trim();
  if (!text) return [];
  const wanted = new Set(
    text
      .split(SEP)
      .map(part => part.trim())
      .filter(Boolean),
  );
  return interaction.passages.filter(p => wanted.has(p.id)).map(p => p.id);
}

/** Toggle one passage id in/out of the selection. */
export function toggleHighlightPassage(selectedIds: string[], passageId: string): string[] {
  const id = passageId.trim();
  if (!id) return selectedIds;
  if (selectedIds.includes(id)) return selectedIds.filter(x => x !== id);
  return [...selectedIds, id];
}
