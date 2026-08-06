"use client";

/**
 * KnowledgeGraph3D — 3D WebGL knowledge-graph visualisation.
 *
 * Backed by `react-force-graph-3d` (Three.js + WebGL). The library
 * handles physics, camera, and picking; we provide the data adapter
 * and custom node objects — a matte sphere + a hidden focus halo +
 * an always-visible SpriteText label per node, built by
 * `nodeThreeObject` and registered in a mutable visuals registry
 * (`visualsRef`) that later tasks mutate directly for hover/highlight
 * styling without rebuilding geometry.
 *
 * SSR: `react-force-graph-3d` calls `document` and `window` at module
 * load. We `dynamic`-import it with `ssr: false` so Next.js doesn't
 * try to render it on the server. Layout-shift is avoided by sizing
 * the wrapper div explicitly to `width × height`.
 */

import React from "react";
import dynamic from "next/dynamic";
import * as THREE from "three";
import SpriteText from "three-spritetext";
import type { GraphEdge, GraphNode } from "@/lib/data";
import { IS_TEST_MODE } from "@/lib/testMode";
import {
  baseNodeColor,
  labelSpec,
  nodeRadius,
  resolveGraphTheme,
  NODE_OPACITY,
  type GraphTheme,
} from "./graph3dHelpers";

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
  // Theme tokens resolved to hex once per mount (three.js can't read
  // CSS vars). Client-only: this component is dynamic({ssr:false}).
  const theme: GraphTheme = React.useMemo(() => resolveGraphTheme(), []);

  type NodeVisual = {
    sphereMat: THREE.MeshLambertMaterial;
    label: SpriteText;
    halo: THREE.Mesh;
    baseColor: string;
  };
  // Mutable registry of every node's restylable parts. Hover/highlight
  // mutate materials through this map — never by rebuilding objects.
  const visualsRef = React.useRef<Map<string, NodeVisual>>(new Map());
  // Refs mirror hover/highlight state so nodeThreeObject (called by the
  // library outside React's render) sees current values without being
  // re-created — re-creating it would rebuild every node's geometry.
  const hoverRef = React.useRef<string | null>(null);
  const highlightRef = React.useRef<string | undefined>(highlightId);
  highlightRef.current = highlightId;

  const graphData = React.useMemo(() => {
    // New data → new registry. Entries repopulate as the library calls
    // nodeThreeObject for each node. (Benign under StrictMode double-
    // invoke: the second call just swaps in another empty map.)
    visualsRef.current = new Map();
    const fgNodes: FG3DNode[] = nodes.map((n) => ({ ...n }));
    const fgLinks: FG3DLink[] = edges.map((e) => ({
      source: e.source,
      target: e.target,
      strength: e.strength,
    }));
    return { nodes: fgNodes, links: fgLinks };
  }, [nodes, edges]);

  const nodeThreeObject = React.useCallback(
    (raw: object) => {
      const n = raw as FG3DNode;
      const r = nodeRadius(n);
      const color = baseNodeColor(n, theme);
      const group = new THREE.Group();

      const sphereMat = new THREE.MeshLambertMaterial({
        color,
        transparent: true,
        opacity: NODE_OPACITY,
      });
      group.add(new THREE.Mesh(new THREE.SphereGeometry(r, 24, 24), sphereMat));

      // Focus halo: slightly larger translucent accent sphere, hidden
      // until this node is hovered or is the persistent highlightId.
      const halo = new THREE.Mesh(
        new THREE.SphereGeometry(r * 1.4, 16, 16),
        new THREE.MeshBasicMaterial({
          color: theme.accent,
          transparent: true,
          opacity: 0.28,
          depthWrite: false,
        }),
      );
      halo.visible = n.id === hoverRef.current || n.id === highlightRef.current;
      group.add(halo);

      const spec = labelSpec(n);
      const label = new SpriteText(n.name);
      label.textHeight = spec.textHeight;
      label.fontWeight = spec.fontWeight;
      label.color = theme.ink;
      label.fontFace = '"JetBrains Mono", monospace';
      label.material.transparent = true;
      label.position.set(0, -(r + spec.textHeight + 1.5), 0);
      group.add(label);

      visualsRef.current.set(n.id, { sphereMat, label, halo, baseColor: color });
      return group;
    },
    [theme],
  );

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
        nodeThreeObject={nodeThreeObject}
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
