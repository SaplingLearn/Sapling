/**
 * W7.2 Dialogue (design kit 7.17) — partner chat ↔ `answerText` for a
 * short_answer wire.
 *
 * DISPLAY + SESSION STATE ONLY. Generation does not emit `interaction` yet;
 * grading still uses the short-answer path on whatever string Check sends.
 * Encode joins student replies with a record separator so decode can restore
 * the thread when the student pages back.
 *
 * Design kit: opening partner line → student reply → fixed follow-up → more
 * replies. Check unlocks once `minReplies` (default 2) are sent; composer
 * caps at `maxReplies` (default 4).
 */

import type { DialogueInteraction, WireQuestion } from "./types";

/** Unlikely in typed prose; keeps reply boundaries stable on round-trip. */
const SEP = "\u001e";

const DEFAULT_MIN = 2;
const DEFAULT_MAX = 4;

function cleanText(raw: unknown, allowEmpty = false): string {
  if (typeof raw !== "string") return "";
  const text = raw.trim();
  if (!allowEmpty && !text) return "";
  return text;
}

function clampCount(raw: unknown, fallback: number, lo: number, hi: number): number {
  if (typeof raw !== "number" || !Number.isFinite(raw)) return fallback;
  const n = Math.floor(raw);
  if (n < lo || n > hi) return fallback;
  return n;
}

/**
 * A usable Dialogue payload: non-empty role / open / follow, sensible reply
 * bounds (1 ≤ min ≤ max ≤ 8).
 */
export function asDialogueInteraction(
  raw: WireQuestion["interaction"] | null | undefined,
): DialogueInteraction | null {
  if (!raw || raw.kind !== "dialogue") return null;
  const role = cleanText(raw.role);
  const open = cleanText(raw.open);
  const follow = cleanText(raw.follow);
  if (!role || !open || !follow) return null;
  let minReplies = clampCount(raw.minReplies, DEFAULT_MIN, 1, 8);
  let maxReplies = clampCount(raw.maxReplies, DEFAULT_MAX, 1, 8);
  if (maxReplies < minReplies) {
    minReplies = DEFAULT_MIN;
    maxReplies = DEFAULT_MAX;
  }
  const placeholder = cleanText(raw.placeholder, true) || undefined;
  return {
    kind: "dialogue",
    role,
    open,
    follow,
    ...(placeholder ? { placeholder } : {}),
    minReplies,
    maxReplies,
  };
}

export function dialogueMinReplies(interaction: DialogueInteraction): number {
  return interaction.minReplies ?? DEFAULT_MIN;
}

export function dialogueMaxReplies(interaction: DialogueInteraction): number {
  return interaction.maxReplies ?? DEFAULT_MAX;
}

/** True when the student has sent at least `minReplies` non-empty messages. */
export function isDialogueComplete(
  interaction: DialogueInteraction,
  raw: string | null | undefined,
): boolean {
  return decodeDialogueAnswer(raw).length >= dialogueMinReplies(interaction);
}

/** Encode student replies for the short_answer wire. */
export function encodeDialogueAnswer(replies: string[]): string {
  return replies
    .map(r => r.trim())
    .filter(Boolean)
    .join(SEP);
}

/** Restore student replies from `answerText`; empty / blank parts dropped. */
export function decodeDialogueAnswer(raw: string | null | undefined): string[] {
  const text = (raw ?? "").trim();
  if (!text) return [];
  return text
    .split(SEP)
    .map(part => part.trim())
    .filter(Boolean);
}

/**
 * Append a reply when under the max and non-empty; otherwise return the
 * prior list unchanged.
 */
export function appendDialogueReply(
  interaction: DialogueInteraction,
  replies: string[],
  next: string,
): string[] {
  const body = next.trim();
  if (!body) return replies;
  if (replies.length >= dialogueMaxReplies(interaction)) return replies;
  return [...replies, body];
}
