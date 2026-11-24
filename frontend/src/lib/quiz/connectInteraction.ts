/**
 * W7.2 Connect (design kit 7.3 match) — left→right pairs ↔ `answerText`.
 *
 * DISPLAY + SESSION STATE ONLY. Generation does not emit `interaction` yet.
 * Encode: `leftId=rightId;…` (Build-shaped). Concept-map mode deferred.
 */

import type { ConnectInteraction, ConnectInteractionNode, WireQuestion } from "./types";

/** left id → right id, or null while unpaired. */
export type ConnectAssignment = Record<string, string | null>;

const SEP_SLOT = ";";
const SEP_NAME = "=";

function safeId(raw: unknown): string {
  if (typeof raw !== "string") return "";
  const id = raw.trim();
  if (!id || id.includes(SEP_SLOT) || id.includes(SEP_NAME)) return "";
  return id;
}

function cleanNodes(raw: ConnectInteractionNode[] | undefined): ConnectInteractionNode[] {
  const seen = new Set<string>();
  const nodes: ConnectInteractionNode[] = [];
  for (const it of raw ?? []) {
    const id = safeId(it?.id);
    const label = typeof it?.label === "string" ? it.label.trim() : "";
    if (!id || !label || seen.has(id)) continue;
    seen.add(id);
    nodes.push({ id, label });
  }
  return nodes;
}

/**
 * A usable Connect payload: ≥2 left, ≥2 right, equal counts, no id overlap.
 */
export function asConnectInteraction(
  raw: WireQuestion["interaction"] | null | undefined,
): ConnectInteraction | null {
  if (!raw || raw.kind !== "connect") return null;
  const left = cleanNodes(raw.left);
  const right = cleanNodes(raw.right);
  if (left.length < 2 || right.length < 2 || left.length !== right.length) return null;
  const rightIds = new Set(right.map(n => n.id));
  if (left.some(n => rightIds.has(n.id))) return null;
  const note = typeof raw.note === "string" && raw.note.trim() ? raw.note.trim() : undefined;
  return {
    kind: "connect",
    left,
    right,
    ...(note ? { note } : {}),
  };
}

export function emptyConnectAssignment(left: ConnectInteractionNode[]): ConnectAssignment {
  return Object.fromEntries(left.map(n => [n.id, null]));
}

export function isConnectComplete(
  interaction: ConnectInteraction,
  assign: ConnectAssignment,
): boolean {
  const rightIds = new Set(interaction.right.map(n => n.id));
  return interaction.left.every(n => {
    const right = assign[n.id];
    return typeof right === "string" && rightIds.has(right);
  });
}

export function encodeConnectAnswer(
  interaction: ConnectInteraction,
  assign: ConnectAssignment,
): string {
  return interaction.left
    .map(n => `${n.id}${SEP_NAME}${assign[n.id] ?? ""}`)
    .join(SEP_SLOT);
}

export function decodeConnectAnswer(
  interaction: ConnectInteraction,
  raw: string | null | undefined,
): ConnectAssignment {
  const assign = emptyConnectAssignment(interaction.left);
  const text = (raw ?? "").trim();
  if (!text) return assign;
  const byLeft = new Set(interaction.left.map(n => n.id));
  const byRight = new Set(interaction.right.map(n => n.id));
  const taken = new Set<string>();
  for (const part of text.split(SEP_SLOT)) {
    const eq = part.indexOf(SEP_NAME);
    if (eq <= 0) continue;
    const leftId = part.slice(0, eq).trim();
    const rightId = part.slice(eq + 1).trim();
    if (!byLeft.has(leftId) || !byRight.has(rightId) || taken.has(rightId)) continue;
    if (assign[leftId] != null) continue;
    assign[leftId] = rightId;
    taken.add(rightId);
  }
  return assign;
}

/** Pair left→right (or clear when right is null). Right already used frees prior left. */
export function pairConnect(
  assign: ConnectAssignment,
  leftId: string,
  rightId: string | null,
): ConnectAssignment {
  if (!(leftId in assign)) return assign;
  const next: ConnectAssignment = { ...assign, [leftId]: rightId };
  if (rightId) {
    for (const [id, at] of Object.entries(assign)) {
      if (id !== leftId && at === rightId) next[id] = null;
    }
  }
  return next;
}
