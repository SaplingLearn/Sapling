"use client";

/**
 * Quiz launcher Map pane (W7.10 / W7.D3) — the student's real course graph
 * in the home side column.
 *
 * Same renderer as Tree / LiveNeighbourhood (`KnowledgeGraph2D` + its ConceptNode
 * marks). Course hubs render for structure but are not quizzable: a click on a
 * concept calls `onPick` (→ `proposal.choose`) and never starts a quiz.
 *
 * // W7.D3: select ≠ start; no Map-local ranking; hide_tree is nav-only — this
 * // pane embeds the graph so Quiz home stays usable when Tree is hidden.
 */

import React from "react";
import { KnowledgeGraph2D } from "@/components/graph/KnowledgeGraph2D";
import { useGraphSize } from "@/components/graph/useGraphSize";
import type { GraphEdge, GraphNode } from "@/lib/data";

/** Before the first measurement (and wherever ResizeObserver is missing). */
const FALLBACK_SIZE = { w: 400, h: 360 };

export interface LauncherMapProps {
  /** Adapted tree nodes (`lib/data` shape), same set TopicsColumn lists. */
  nodes: GraphNode[];
  edges: GraphEdge[];
  /** `"all"`, or one course id — same filter as the topic pills. */
  courseFilter: string;
  /** The lead card's concept, when any. */
  highlightId?: string | null;
  /** A quizzable node was clicked — pick only, never start. */
  onPick: (nodeId: string) => void;
  /**
   * Optional W3.2 practiced outline. Omit when the home has no learner_state
   * (quiz home today); SessionMap / tutor turns feed it when available.
   */
  practicedIds?: ReadonlySet<string> | readonly string[];
}

/** Course-scoped subgraph: All = union; one course = that course's nodes + edges. */
export function graphForCourse(
  nodes: GraphNode[],
  edges: GraphEdge[],
  courseFilter: string,
): { nodes: GraphNode[]; edges: GraphEdge[] } {
  if (courseFilter === "all") return { nodes, edges };
  const filtered = nodes.filter(n => n.course_id === courseFilter);
  const ids = new Set(filtered.map(n => n.id));
  return {
    nodes: filtered,
    edges: edges.filter(e => ids.has(e.source) && ids.has(e.target)),
  };
}

export function LauncherMap({
  nodes,
  edges,
  courseFilter,
  highlightId,
  onPick,
  practicedIds,
}: LauncherMapProps) {
  const fragment = React.useMemo(
    () => graphForCourse(nodes, edges, courseFilter),
    [nodes, edges, courseFilter],
  );

  const [measure, size] = useGraphSize<HTMLDivElement>(FALLBACK_SIZE);

  const pick = React.useCallback(
    (n: GraphNode) => {
      if (n.is_subject_root) return;
      onPick(n.id);
    },
    [onPick],
  );

  return (
    <div
      ref={measure}
      className="quiz-home__map"
      role="group"
      aria-label="Your knowledge map — click a concept to make it today's quiz"
      data-testid="quiz-launcher-map"
    >
      {fragment.nodes.length === 0 ? (
        <p className="quiz-home__topics-empty" data-testid="quiz-launcher-map-empty">
          No concepts on the map
        </p>
      ) : (
        size && (
          <KnowledgeGraph2D
            nodes={fragment.nodes}
            edges={fragment.edges}
            width={size.w}
            height={size.h}
            highlightId={highlightId ?? undefined}
            onNodeClick={pick}
            practicedIds={practicedIds}
            fit
          />
        )
      )}
    </div>
  );
}
