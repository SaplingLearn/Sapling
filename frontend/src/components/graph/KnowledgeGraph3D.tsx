"use client";

/**
 * KnowledgeGraph3D — 3D WebGL knowledge-graph visualisation.
 *
 * Backed by `react-force-graph-3d` (Three.js + WebGL). The library
 * handles physics + rendering; we provide the data adapter and the
 * styling callbacks (per-node colour shading, highlight, click).
 *
 * SSR: `react-force-graph-3d` calls `document` and `window` at module
 * load. We `dynamic`-import it with `ssr: false` so Next.js doesn't
 * try to render it on the server. Layout-shift is avoided by sizing
 * the wrapper div explicitly to `width × height`.
 *
 * #538: NEVER mount this component outside the `KnowledgeGraph`
 * wrapper — three r163+ throws from the WebGLRenderer constructor when
 * WebGL2 is unavailable, and the wrapper owns both the capability gate
 * that prevents that mount and the error boundary that contains it.
 */

import React from "react";
import dynamic from "next/dynamic";
import { type GraphEdge, type GraphNode } from "@/lib/data";
import { radiusFor, shadeFor } from "@/lib/graph/nodeStyle";
import { IS_TEST_MODE } from "@/lib/testMode";

// `react-force-graph-3d`'s default export touches `document` at
// module evaluation, so it can't be SSR'd. ssr: false ensures the
// import only fires in the browser. The fallback renders nothing —
// callers already wrap us in their own skeleton on first paint.
const ForceGraph3D = dynamic(
  () => import("react-force-graph-3d").then((m) => m.default),
  { ssr: false, loading: () => null },
);

type Props = {
  nodes: GraphNode[];
  edges: GraphEdge[];
  width?: number;
  height?: number;
  highlightId?: string;
  onNodeClick?: (n: GraphNode) => void;
};

// The pure node-style layer (`hexToHsl` / `hslToHex` / `shadeFor`) lives in
// `lib/graph/nodeStyle` (#537) — it was byte-duplicated here and in
// KnowledgeGraph2D. This renderer takes the "hex" form: Three.js's
// `Color.setStyle` only accepts the comma-separated `hsl(h, s%, l%)` syntax,
// and the modern space-separated string the 2D path uses silently renders
// BLACK.

type FG3DNode = GraphNode & {
  x?: number;
  y?: number;
  z?: number;
};

type FG3DLink = {
  source: string;
  target: string;
  strength: number;
};

const SR_ONLY: React.CSSProperties = {
  position: "absolute",
  width: 1,
  height: 1,
  padding: 0,
  margin: -1,
  overflow: "hidden",
  clip: "rect(0,0,0,0)",
  whiteSpace: "nowrap",
  border: 0,
};

export function KnowledgeGraph3D({
  nodes,
  edges,
  width = 800,
  height = 480,
  highlightId,
  onNodeClick,
}: Props) {
  // HYDRATION CONSTRAINT: this value is client-only. SSR returns
  // `false` (window undefined); the client may compute `true`. That
  // mismatch is safe today because `reducedMotion` only flows into
  // `cooldownTicks` on `<ForceGraph3D>`, which is `dynamic({ ssr:
  // false, loading: () => null })` — its props never reach the SSR
  // DOM. If you ever wire `reducedMotion` into the sr-only list,
  // outer <div> styling, or anything else that renders during SSR,
  // gate it behind a `mounted` flag (`useState(false) + useEffect`)
  // or you'll get a React hydration warning.
  const [reducedMotion, setReducedMotion] = React.useState(() => {
    if (typeof window === "undefined") return false;
    return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  });
  React.useEffect(() => {
    if (typeof window === "undefined") return;
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    const onChange = (e: MediaQueryListEvent) => setReducedMotion(e.matches);
    if (mq.addEventListener) mq.addEventListener("change", onChange);
    else mq.addListener(onChange);
    return () => {
      if (mq.removeEventListener) mq.removeEventListener("change", onChange);
      else mq.removeListener(onChange);
    };
  }, []);
  const graphData = React.useMemo(() => {
    const fgNodes: FG3DNode[] = nodes.map((n) => ({ ...n }));
    const fgLinks: FG3DLink[] = edges.map((e) => ({
      source: e.source,
      target: e.target,
      strength: e.strength,
    }));
    return { nodes: fgNodes, links: fgLinks };
  }, [nodes, edges]);

  const nodeColor = React.useCallback(
    (raw: object) => {
      const n = raw as FG3DNode;
      if (n.id === highlightId) return "#8a9a5b";
      return shadeFor(n.color || "#8a9a5b", n.id, "hex");
    },
    [highlightId],
  );

  const nodeLabel = React.useCallback((raw: object) => {
    const n = raw as FG3DNode;
    return n.name;
  }, []);

  const nodeVal = React.useCallback((raw: object) => {
    const n = raw as FG3DNode;
    // Course (root) nodes anchor each family — render them noticeably
    // larger than concept nodes so the eye lands on the family center
    // first. Concept nodes scale 4..10 with mastery_score.
    // NOT `radiusFor`: react-force-graph reads this as a sphere VOLUME, not a
    // radius, and it has always used its own 4..10 ramp. Only the root's flat
    // 22 is shared with the 2D mark.
    if (n.is_subject_root) return radiusFor(0, true);
    return 4 + (typeof n.mastery_score === "number" ? n.mastery_score : 0) * 6;
  }, []);

  const nodesById = React.useMemo(() => {
    const m = new Map<string, GraphNode>();
    for (const n of nodes) m.set(n.id, n);
    return m;
  }, [nodes]);

  const handleNodeClick = React.useCallback(
    (raw: object) => {
      if (!onNodeClick) return;
      const n = raw as FG3DNode;
      const original = nodesById.get(n.id);
      if (original) onNodeClick(original);
    },
    [onNodeClick, nodesById],
  );

  return (
    <div style={{ width, height, position: "relative" }}>
      <ForceGraph3D
        width={width}
        height={height}
        graphData={graphData}
        nodeId="id"
        nodeLabel={nodeLabel}
        nodeColor={nodeColor}
        nodeVal={nodeVal}
        nodeOpacity={0.95}
        nodeResolution={16}
        linkColor={() => "rgba(138, 131, 114, 0.45)"}
        linkOpacity={0.4}
        linkWidth={(l: object) => {
          const link = l as FG3DLink;
          return 0.4 + (link.strength || 0) * 0.6;
        }}
        backgroundColor="rgba(0,0,0,0)"
        showNavInfo={false}
        cooldownTicks={reducedMotion || IS_TEST_MODE ? 0 : 120}
        enableNodeDrag={false}
        onNodeClick={handleNodeClick}
      />
      {/* Same testid seam as the 2D variant (docs/frontend-testids.md, #395):
          only one of the two graph implementations mounts at a time, so the
          shared testids never collide in the DOM. */}
      <ul style={SR_ONLY} aria-label="Knowledge graph nodes" data-testid="graph-node-items">
        {nodes.map((n) =>
          onNodeClick ? (
            <li key={n.id} data-testid="graph-node-item" data-node-id={n.id}>
              <button type="button" data-testid="graph-node-activate" onClick={() => onNodeClick(n)}>
                {n.name}
              </button>
            </li>
          ) : (
            <li key={n.id} data-testid="graph-node-item" data-node-id={n.id}>
              {n.name}
            </li>
          ),
        )}
      </ul>
    </div>
  );
}
