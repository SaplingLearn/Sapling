/**
 * W7.2 Connect — match (7.3) or concept-map mode ↔ `answerText`.
 *
 * DISPLAY + SESSION STATE ONLY. Generation does not emit `interaction` yet.
 * Match encode: `leftId=rightId;…`
 * Map encode: undirected `a=b;c=d` with each pair sorted by id.
 */

import type { ConnectInteraction, ConnectInteractionNode, WireQuestion } from "./types";

/** left id → right id, or null while unpaired (match mode). */
export type ConnectAssignment = Record<string, string | null>;

/** Undirected edge endpoints (map mode). */
export type ConnectMapEdge = { a: string; b: string };

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

export function isConnectMap(interaction: ConnectInteraction): boolean {
  return interaction.mode === "map";
}

/**
 * A usable Connect payload:
 * - match (default): ≥2 left, ≥2 right, equal counts, no id overlap
 * - map: ≥3 nodes, mode "map"
 */
export function asConnectInteraction(
  raw: WireQuestion["interaction"] | null | undefined,
): ConnectInteraction | null {
  if (!raw || raw.kind !== "connect") return null;
  const note = typeof raw.note === "string" && raw.note.trim() ? raw.note.trim() : undefined;

  if (raw.mode === "map") {
    const nodes = cleanNodes(raw.nodes);
    if (nodes.length < 3) return null;
    return {
      kind: "connect",
      mode: "map",
      nodes,
      left: [],
      right: [],
      ...(note ? { note } : {}),
    };
  }

  const left = cleanNodes(raw.left);
  const right = cleanNodes(raw.right);
  if (left.length < 2 || right.length < 2 || left.length !== right.length) return null;
  const rightIds = new Set(right.map(n => n.id));
  if (left.some(n => rightIds.has(n.id))) return null;
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
  if (isConnectMap(interaction)) return false;
  const rightIds = new Set(interaction.right.map(n => n.id));
  return interaction.left.every(n => {
    const right = assign[n.id];
    return typeof right === "string" && rightIds.has(right);
  });
}

/** Map complete when every node is incident to ≥1 edge and ≥ n−1 edges (tree-ish). */
export function isConnectMapComplete(
  interaction: ConnectInteraction,
  edges: readonly ConnectMapEdge[],
): boolean {
  if (!isConnectMap(interaction)) return false;
  const nodes = interaction.nodes ?? [];
  const n = nodes.length;
  if (n < 3 || edges.length < n - 1) return false;
  const seen = new Set<string>();
  for (const e of edges) {
    seen.add(e.a);
    seen.add(e.b);
  }
  return nodes.every(node => seen.has(node.id));
}

export function encodeConnectAnswer(
  interaction: ConnectInteraction,
  assign: ConnectAssignment,
): string {
  return interaction.left
    .map(n => `${n.id}${SEP_NAME}${assign[n.id] ?? ""}`)
    .join(SEP_SLOT);
}

export function edgeKey(a: string, b: string): string {
  return a < b ? `${a}${SEP_NAME}${b}` : `${b}${SEP_NAME}${a}`;
}

export function encodeConnectMapAnswer(edges: readonly ConnectMapEdge[]): string {
  const keys = [...new Set(edges.map(e => edgeKey(e.a, e.b)))].sort();
  return keys.join(SEP_SLOT);
}

export function decodeConnectAnswer(
  interaction: ConnectInteraction,
  raw: string | null | undefined,
): ConnectAssignment {
  const assign = emptyConnectAssignment(interaction.left);
  const text = (raw ?? "").trim();
  if (!text || isConnectMap(interaction)) return assign;
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

export function decodeConnectMapAnswer(
  interaction: ConnectInteraction,
  raw: string | null | undefined,
): ConnectMapEdge[] {
  if (!isConnectMap(interaction)) return [];
  const byId = new Set((interaction.nodes ?? []).map(n => n.id));
  const text = (raw ?? "").trim();
  if (!text) return [];
  const out: ConnectMapEdge[] = [];
  const seen = new Set<string>();
  for (const part of text.split(SEP_SLOT)) {
    const eq = part.indexOf(SEP_NAME);
    if (eq <= 0) continue;
    const a = part.slice(0, eq).trim();
    const b = part.slice(eq + 1).trim();
    if (!byId.has(a) || !byId.has(b) || a === b) continue;
    const k = edgeKey(a, b);
    if (seen.has(k)) continue;
    seen.add(k);
    out.push(a < b ? { a, b } : { a: b, b: a });
  }
  return out;
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

/** Toggle an undirected edge among map nodes. */
export function toggleConnectMapEdge(
  edges: readonly ConnectMapEdge[],
  a: string,
  b: string,
): ConnectMapEdge[] {
  if (a === b) return [...edges];
  const k = edgeKey(a, b);
  if (edges.some(e => edgeKey(e.a, e.b) === k)) {
    return edges.filter(e => edgeKey(e.a, e.b) !== k);
  }
  return [...edges, a < b ? { a, b } : { a: b, b: a }];
}
