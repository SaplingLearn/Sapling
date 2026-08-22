/**
 * neighbourhood — which concepts to draw around a centre concept.
 *
 * There is no neighbourhood endpoint: `GET /api/graph/{user}` returns the
 * whole `{nodes, edges}` and the caller derives the fragment. This module is
 * that derivation, kept pure and deterministic so the little constellation on
 * quiz home doesn't reshuffle between renders (#537).
 *
 * Two sources, in order:
 *   1. Real neighbours — the other endpoint of any edge touching the centre,
 *      strongest first. `subject_root__*` hubs are excluded: the backend mints
 *      one per course and wires it to *every* concept in that course
 *      (graph_service.py), so they are structure, not siblings.
 *   2. Backfill — same-course concepts, ordered by `hashSeed(id)`. A freshly
 *      extracted concept often has no edges at all, and an empty
 *      neighbourhood reads as "this concept is alone on your tree", which is
 *      a lie about the data rather than a fact about it.
 */

import { hashSeed, type GraphEdge, type GraphNode } from "@/lib/data";

/** The synthetic per-course hub id minted by `graph_service.get_graph`. */
const SUBJECT_ROOT_PREFIX = "subject_root__";

export interface NeighbourNode {
  id: string;
  name: string;
  mastery: number;
  tier: string;
  /** Edge strength to the centre. Backfilled peers get the backend's fixed
   *  hub-spoke 0.7 so their edge renders at the same width as a real spoke. */
  strength: number;
}

/** The strength `graph_service` gives every hub-spoke edge. */
export const BACKFILL_STRENGTH = 0.7;

const isRoot = (n: Pick<GraphNode, "id" | "is_subject_root">) =>
  Boolean(n.is_subject_root) || n.id.startsWith(SUBJECT_ROOT_PREFIX);

function toNeighbour(node: GraphNode, strength: number): NeighbourNode {
  return {
    id: node.id,
    name: node.name,
    mastery: node.mastery_score || 0,
    tier: node.mastery_tier,
    strength,
  };
}

/**
 * Up to `n` siblings for `centreId`, deterministic for a given graph.
 *
 * Returns fewer than `n` only when the course genuinely has fewer concepts.
 * An unknown `centreId` yields an empty list rather than a random selection —
 * the caller has nothing to draw a centre for either.
 */
export function siblingsFor(
  centreId: string,
  nodes: GraphNode[],
  edges: GraphEdge[],
  n = 3,
): NeighbourNode[] {
  if (n <= 0) return [];
  const byId = new Map(nodes.map((node) => [node.id, node]));
  const centre = byId.get(centreId);
  if (!centre) return [];

  // 1. Real neighbours, strongest first. A pair can be joined by more than one
  //    edge, so keep the strongest per id; ties break on id for stability
  //    (Array.prototype.sort is stable, but the input edge order is not).
  const strongest = new Map<string, number>();
  for (const e of edges) {
    const otherId = e.source === centreId ? e.target : e.target === centreId ? e.source : null;
    if (!otherId || otherId === centreId) continue;
    const other = byId.get(otherId);
    if (!other || isRoot(other)) continue;
    const strength = e.strength ?? 0;
    const seen = strongest.get(otherId);
    if (seen === undefined || strength > seen) strongest.set(otherId, strength);
  }

  const picked: NeighbourNode[] = [...strongest.entries()]
    .sort((a, b) => b[1] - a[1] || (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0))
    .slice(0, n)
    .map(([id, strength]) => toNeighbour(byId.get(id)!, strength));

  if (picked.length >= n) return picked;

  // 2. Backfill with same-course peers the edges didn't already supply.
  const taken = new Set(picked.map((p) => p.id));
  taken.add(centreId);
  const peers = nodes
    .filter(
      (node) =>
        !taken.has(node.id) &&
        !isRoot(node) &&
        node.course_id === centre.course_id &&
        // A blank course_id matches every other blank one — that is noise, not
        // a course. Skip the backfill entirely rather than invent a family.
        Boolean(centre.course_id),
    )
    .sort((a, b) => hashSeed(a.id) - hashSeed(b.id) || (a.id < b.id ? -1 : 1));

  for (const peer of peers) {
    if (picked.length >= n) break;
    picked.push(toNeighbour(peer, BACKFILL_STRENGTH));
  }

  return picked;
}
