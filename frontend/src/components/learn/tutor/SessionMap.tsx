"use client";
import React, { useEffect, useMemo, useRef, useState } from "react";
import type { GraphEdge, GraphNode } from "@/lib/data";
import { KnowledgeGraph } from "../../graph/KnowledgeGraph";
import styles from "./tutor.module.css";

/** The map's height in the session panel. */
const SESSION_MAP_HEIGHT = 240;

/**
 * What the session panel's map draws: the course's concepts and the links
 * between them, without the course root. The panel covers one course, so the
 * root says nothing the panel does not, and the key under the map has no
 * entry for it: drawn at the tree's flat course size and in hub brown it read
 * as an unexplained blob beside the concepts. The layout plans rootless
 * concepts round their group's middle (`radialLayout.planCourse`).
 */
export function sessionMapGraph(
  nodes: readonly GraphNode[],
  edges: readonly GraphEdge[],
): { nodes: GraphNode[]; edges: GraphEdge[] } {
  const concepts = nodes.filter((n) => !n.is_subject_root);
  const ids = new Set(concepts.map((n) => n.id));
  return {
    nodes: concepts,
    edges: edges.filter((e) => ids.has(e.source as string) && ids.has(e.target as string)),
  };
}

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
 *     practiced this session (`practicedNodeIds`: graded answers only).
 * Width is measured (the panel's own), as Learn.tsx's sidebar graph does.
 * Only concepts are drawn (`sessionMapGraph`); with none there is no map.
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
  /** Node ids graded this session: a graded turn's on screen, or named by GET /status (a resume). */
  practicedNodeIds?: ReadonlySet<string> | readonly string[];
}) {
  const graph = useMemo(() => sessionMapGraph(nodes, edges), [nodes, edges]);
  const hasConcepts = graph.nodes.length > 0;
  const [width, setWidth] = useState(0);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver((entries) => setWidth(entries[0].contentRect.width));
    ro.observe(el);
    return () => ro.disconnect();
    // Re-measure when the map first appears: with no concepts there is no box.
  }, [hasConcepts]);
  if (!hasConcepts) return null;
  return (
    <div ref={ref} data-testid="tutor-session-map" className={styles.sessionMap}>
      {width > 0 && (
        <KnowledgeGraph
          nodes={graph.nodes}
          edges={graph.edges}
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
