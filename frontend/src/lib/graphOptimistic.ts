/**
 * Pure state math for the manual add-concept flow (#330).
 *
 * The UI adds an optimistic `node-new-<ts>` entry (and its anchor edge)
 * immediately, then POST /api/graph/{user}/nodes returns the CANONICAL row —
 * either freshly created or the UNIQUE-dedup survivor of a case/whitespace
 * merge. These helpers swap the optimistic id for the canonical one across
 * the two state collections (nodes and edges live in separate useStates, so
 * each helper touches exactly one and works inside a functional updater),
 * and roll the optimistic entry back when the write fails.
 */

export interface OptimisticNode {
  id: string;
  mastery_score?: number;
  mastery_tier?: string;
  [key: string]: unknown;
}

export interface OptimisticEdge {
  source: string;
  target: string;
  [key: string]: unknown;
}

export interface CanonicalNode {
  id: string;
  mastery_score?: number;
  mastery_tier?: string;
}

/** Swap the optimistic node for the canonical row. When the canonical id is
 * already rendered (the name merged into an existing node), the optimistic
 * entry is simply dropped. */
export function reconcileNodes<N extends OptimisticNode>(
  nodes: N[],
  tempId: string,
  canonical: CanonicalNode,
): N[] {
  if (nodes.some((n) => n.id === canonical.id)) {
    return nodes.filter((n) => n.id !== tempId);
  }
  return nodes.map((n) =>
    n.id === tempId
      ? {
          ...n,
          id: canonical.id,
          mastery_score: canonical.mastery_score ?? n.mastery_score,
          mastery_tier: canonical.mastery_tier ?? n.mastery_tier,
        }
      : n,
  );
}

/** Retarget edges touching the optimistic id onto the canonical id, dropping
 * the self-loops and duplicates a merge can create. */
export function retargetEdges<E extends OptimisticEdge>(
  edges: E[],
  tempId: string,
  canonicalId: string,
): E[] {
  const out: E[] = [];
  const seen = new Set<string>();
  for (const edge of edges) {
    const source = edge.source === tempId ? canonicalId : edge.source;
    const target = edge.target === tempId ? canonicalId : edge.target;
    if (source === target) continue;
    const key = `${source}→${target}`;
    if (seen.has(key)) continue;
    seen.add(key);
    out.push({ ...edge, source, target });
  }
  return out;
}

/** Roll back a failed add: remove the optimistic node and every edge touching it. */
export function dropOptimisticConcept<N extends OptimisticNode, E extends OptimisticEdge>(
  nodes: N[],
  edges: E[],
  tempId: string,
): { nodes: N[]; edges: E[] } {
  return {
    nodes: nodes.filter((n) => n.id !== tempId),
    edges: edges.filter((e) => e.source !== tempId && e.target !== tempId),
  };
}
