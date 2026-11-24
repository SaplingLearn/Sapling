"use client";
import React, { useEffect, useRef, useState } from "react";
import type { GraphEdge, GraphNode } from "@/lib/data";
import { KnowledgeGraph } from "../../graph/KnowledgeGraph";

/** The map's height in the session panel. */
const SESSION_MAP_HEIGHT = 240;

/**
 * The session panel's knowledge map (wireframe F, "Knowledge map"): the
 * course's concepts, the one being taught highlighted. A small overview — the
 * full map is a link away — so it is drawn the one way its key (under it, in
 * `SessionPanel`) describes:
 *   - in mastery colours, fixed: no colour toggle, whatever the Tree is set to;
 *   - framed so every concept and its whole caption is inside the panel, with
 *     no zoom stack over the nodes. It follows the layout until the student
 *     pans, drags or pinch-zooms it; a double-click re-frames it, and so does
 *     a new set of concepts. A plain wheel scrolls the panel, never the map.
 *   - W3.2 dual encoding: fill = understood (mastery); solid outline =
 *     practiced this session (`practicedNodeIds` from measured learner_state).
 * Width is measured (the panel's own), as Learn.tsx's sidebar graph does.
 */
export function SessionMap({
  nodes,
  edges,
  highlightId,
  practicedNodeIds,
}: {
  nodes: GraphNode[];
  edges: GraphEdge[];
  highlightId?: string;
  /** Node ids with a measured learner_state entry this session (covered/practiced). */
  practicedNodeIds?: ReadonlySet<string> | readonly string[];
}) {
  const [width, setWidth] = useState(0);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver((entries) => setWidth(entries[0].contentRect.width));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return (
    <div ref={ref} data-testid="tutor-session-map" style={{ width: "100%" }}>
      {width > 0 && (
        <KnowledgeGraph
          nodes={nodes}
          edges={edges}
          width={width}
          height={SESSION_MAP_HEIGHT}
          highlightId={highlightId}
          practicedIds={practicedNodeIds}
          colorMode="mastery"
          fit
          zoomControls={false}
          wheelZoom="pinch"
        />
      )}
    </div>
  );
}
