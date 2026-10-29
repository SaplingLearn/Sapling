"use client";

/**
 * The proposal's neighbourhood as a live fragment of the tree.
 *
 * The tree's own 2D renderer (`KnowledgeGraph2D`), fed only the proposed
 * concept and the neighbours `siblingsFor` picks — real neighbours strongest
 * first, backfilled with same-course concepts when the concept has few edges
 * (a fresh concept often has none, and a lone node in a window reads as "this
 * is alone on your tree", which is not true). It settles under the same
 * simulation, drags, pans and zooms like the tree, and clicking a neighbour
 * opens that concept's quiz dialog. The 2D renderer is used directly rather
 * than through `KnowledgeGraph`: a 2D/3D toggle has no room in a window this
 * size, and flipping it here would rewrite the student's tree preference.
 *
 * Course hubs (`is_subject_root`) are left out — they are not quizzable, and
 * every concept hangs off one, so they would crowd out the real neighbours.
 * A backfilled peer is joined to the centre at the hub-spoke strength, the
 * same stand-in the static neighbourhood draws.
 */

import React from "react";
import { KnowledgeGraph2D } from "@/components/graph/KnowledgeGraph2D";
import type { GraphEdge, GraphNode } from "@/lib/data";
import { siblingsFor } from "@/lib/graph/neighbourhood";

/** How many neighbours the window shows, strongest edges first. */
const MAX_NEIGHBOURS = 8;
/** Before the first measurement (and wherever ResizeObserver is missing). */
const FALLBACK_SIZE = { w: 500, h: 340 };
/** The fragment settles to a cluster about the size of the tree's own spacing;
 *  this zooms it to fill the window instead of floating in the middle. */
const INITIAL_ZOOM = 1.6;

export interface LiveNeighbourhoodProps {
  centreId: string;
  /** The whole tree, adapted (`lib/data` shape). */
  nodes: GraphNode[];
  edges: GraphEdge[];
  /** A neighbour was clicked. The centre is already the proposal. */
  onPick: (nodeId: string) => void;
  ariaLabel: string;
}

export function LiveNeighbourhood({ centreId, nodes, edges, onPick, ariaLabel }: LiveNeighbourhoodProps) {
  const fragment = React.useMemo(() => {
    const neighbours = siblingsFor(centreId, nodes, edges, MAX_NEIGHBOURS);
    const ids = new Set([centreId, ...neighbours.map(n => n.id)]);
    const real = edges.filter(e => ids.has(e.source) && ids.has(e.target));
    const touching = (id: string) =>
      real.some(e => (e.source === centreId && e.target === id) || (e.target === centreId && e.source === id));
    const backfilled = neighbours
      .filter(n => !touching(n.id))
      .map(n => ({ source: centreId, target: n.id, strength: n.strength }));
    return {
      nodes: nodes.filter(n => ids.has(n.id)),
      edges: [...real, ...backfilled],
    };
  }, [centreId, nodes, edges]);

  // Callback ref, as on the dashboard: the window can mount after the first
  // render (the skeleton comes first), and a plain ref + effect would miss it.
  const [size, setSize] = React.useState(FALLBACK_SIZE);
  const observer = React.useRef<ResizeObserver | null>(null);
  const measure = React.useCallback((el: HTMLDivElement | null) => {
    observer.current?.disconnect();
    observer.current = null;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(entries => {
      for (const entry of entries) {
        const { width, height } = entry.contentRect;
        if (width > 0 && height > 0) setSize({ w: width, h: height });
      }
    });
    ro.observe(el);
    observer.current = ro;
  }, []);

  const pick = React.useCallback(
    (n: GraphNode) => {
      if (n.id !== centreId) onPick(n.id);
    },
    [centreId, onPick],
  );

  return (
    <div
      ref={measure}
      className="quiz-home__neighbourhood"
      role="group"
      aria-label={ariaLabel}
      data-testid="quiz-neighbourhood"
    >
      <KnowledgeGraph2D
        nodes={fragment.nodes}
        edges={fragment.edges}
        width={size.w}
        height={size.h}
        highlightId={centreId}
        onNodeClick={pick}
        initialZoom={INITIAL_ZOOM}
      />
    </div>
  );
}
