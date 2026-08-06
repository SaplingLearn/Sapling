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
import type { ForceGraphMethods, ForceGraphProps } from "react-force-graph-3d";
import type { GraphEdge, GraphNode } from "@/lib/data";
import { IS_TEST_MODE } from "@/lib/testMode";
import {
  baseNodeColor,
  buildAdjacency,
  hexToRgbTriplet,
  labelSpec,
  nodeRadius,
  resolveGraphTheme,
  NODE_OPACITY,
  BASE_LINK_ALPHA,
  LIT_LINK_ALPHA,
  DIM_LINK_ALPHA,
  DIM_NODE_OPACITY,
  DIM_LABEL_OPACITY,
  type GraphTheme,
} from "./graph3dHelpers";

// `react-force-graph-3d`'s default export touches `document` at
// module evaluation, so it can't be SSR'd. ssr: false ensures the
// import only fires in the browser. The fallback renders nothing —
// callers already wrap us in their own skeleton on first paint.
//
// next/dynamic can't forward refs, and we need the instance for
// zoomToFit. The loader wraps the lib component so the ref rides in as
// a regular `fgRef` prop. Type-only imports above are erased at
// compile time — nothing here reaches the server bundle.
type FGRefProp = { fgRef?: React.MutableRefObject<ForceGraphMethods | undefined> };
const ForceGraph3D = dynamic(
  () =>
    import("react-force-graph-3d").then((m) => {
      const FG = m.default;
      const WithRef = ({ fgRef, ...rest }: ForceGraphProps & FGRefProp) => (
        <FG {...rest} ref={fgRef} />
      );
      return WithRef;
    }),
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
  source: string | FG3DNode;
  target: string | FG3DNode;
  strength: number;
};

// The library swaps string ids for node-object refs once the
// simulation starts, so link accessors must accept either shape.
const linkEndId = (v: unknown): string =>
  typeof v === "object" && v !== null ? (v as FG3DNode).id : (v as string);

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
  // Imperative handle to the mounted lib instance — bridged in via the
  // dynamic wrapper's `fgRef` prop (next/dynamic strips real refs).
  const fgRef = React.useRef<ForceGraphMethods | undefined>(undefined);
  // Guards the initial camera auto-fit (below) to once per dataset — reset
  // in the effect below whenever nodes/edges change. Without the guard, any
  // later onEngineStop (the library re-settling, e.g. after a drag) would
  // re-fit the camera out from under a user who has since panned/zoomed.
  const didFitRef = React.useRef(false);
  // Bumped alongside didFitRef.current = false whenever nodes/edges change.
  // The bbox-stabilization poll (handleEngineStop, below) captures this
  // value at poll start and every scheduled frame re-checks it against the
  // live counter — a poll from a stale dataset bails out instead of firing
  // zoomToFit and clobbering the fresh poll's correct fit for the new data
  // (round 3 fix: a dataset change mid-poll, up to ~1s/MAX_FRAMES wide,
  // otherwise let the old closure win the race).
  const pollEpochRef = React.useRef(0);
  // Tracks the currently-scheduled rAF id so an unmount mid-poll can cancel
  // it (round 3 hygiene fix) instead of leaving up to MAX_FRAMES dangling
  // no-op callbacks.
  const pollRafIdRef = React.useRef<number | null>(null);
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

  // Reset the auto-fit once-guard whenever the dataset changes. Runs after
  // the render that produced the new graphData commits — well before the
  // library's next onEngineStop for these nodes/edges can fire — so the
  // camera is re-fit exactly once for each new dataset. Bumping
  // pollEpochRef here invalidates any in-flight poll from the PREVIOUS
  // dataset — its stale closure checks this counter every frame and bails
  // instead of firing zoomToFit against data that's no longer current.
  React.useEffect(() => {
    didFitRef.current = false;
    pollEpochRef.current += 1;
  }, [nodes, edges]);

  // Cancel any in-flight bbox-stabilization poll on unmount so it can't
  // leave dangling rAF callbacks running against an unmounted instance.
  React.useEffect(() => {
    return () => {
      if (pollRafIdRef.current !== null) cancelAnimationFrame(pollRafIdRef.current);
    };
  }, []);

  const adjacency = React.useMemo(() => buildAdjacency(edges), [edges]);
  // hoverId lives in state ONLY to re-key the link accessors below; the
  // node/label/halo restyle happens imperatively via visualsRef.
  const [hoverId, setHoverId] = React.useState<string | null>(null);

  const applyFocus = React.useCallback(
    (hover: string | null) => {
      hoverRef.current = hover;
      const neighbors = hover ? adjacency.get(hover) : undefined;
      for (const [id, v] of visualsRef.current) {
        const lit = !hover || id === hover || (neighbors?.has(id) ?? false);
        v.sphereMat.color.set(lit ? v.baseColor : theme.dim);
        v.sphereMat.opacity = lit ? NODE_OPACITY : DIM_NODE_OPACITY;
        v.label.material.opacity = lit ? 1 : DIM_LABEL_OPACITY;
        v.halo.visible = id === hover || id === highlightRef.current;
      }
    },
    [adjacency, theme],
  );

  const handleNodeHover = React.useCallback(
    (raw: object | null) => {
      const id = raw ? (raw as FG3DNode).id : null;
      setHoverId(id);
      applyFocus(id);
    },
    [applyFocus],
  );

  // Re-assert focus when highlightId/adjacency/theme change (e.g. the
  // tutor moves the discussed node while the user isn't hovering).
  React.useEffect(() => {
    applyFocus(hoverRef.current);
  }, [applyFocus, highlightId]);

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

  // Single source for the lit-link rgb: derived from theme.accent (the same
  // token the focus halo uses), never a second hardcoded copy — otherwise
  // the halo and its own lit edges can silently drift apart (found in the
  // final-review pass: the halo already read theme.accent, but linkColor
  // still hardcoded the retired sage rgb, so production rendered a forest
  // halo next to sage-colored lit edges).
  const litLinkRgbTriplet = React.useMemo(() => hexToRgbTriplet(theme.accent), [theme]);

  const linkColor = React.useCallback(
    (l: object) => {
      const link = l as FG3DLink;
      if (!hoverId) return `rgba(138, 131, 114, ${BASE_LINK_ALPHA})`;
      const lit = linkEndId(link.source) === hoverId || linkEndId(link.target) === hoverId;
      // Lit links take the theme accent; dimmed links fade to near-invisible
      // warm gray.
      return lit
        ? `rgba(${litLinkRgbTriplet}, ${LIT_LINK_ALPHA})`
        : `rgba(138, 131, 114, ${DIM_LINK_ALPHA})`;
    },
    [hoverId, litLinkRgbTriplet],
  );

  const linkWidth = React.useCallback(
    (l: object) => {
      const link = l as FG3DLink;
      const base = 0.4 + (link.strength || 0) * 0.6;
      if (!hoverId) return base;
      const lit = linkEndId(link.source) === hoverId || linkEndId(link.target) === hoverId;
      return lit ? base + 0.6 : base;
    },
    [hoverId],
  );

  // Auto-fit the camera the first time the force engine settles for this
  // dataset — otherwise the initial camera distance never frames the graph
  // and every node renders as an illegible clump at the center of the
  // canvas (found in the Task 5 visual pass). didFitRef makes this
  // idempotent per dataset so a later re-settle (e.g. after a drag) can't
  // yank the camera back after the user has since panned/zoomed.
  //
  // ROOT CAUSE (confirmed via node_modules/3d-force-graph's tickFrame
  // source plus live frame-by-frame logging against a running dev server —
  // Task 5 round 2): onEngineStop fires synchronously *before* tickFrame's
  // "update node positions" step writes that tick's x/y/z onto each node's
  // Three.js object — both happen inside the same synchronous layoutTick()
  // call, stop-callback first. Fitting synchronously (or even one rAF
  // later) therefore measures the scene before the current tick's
  // positions — and, under cooldownTicks={0} (test/reduced-motion mode),
  // Three.js's matrixWorld propagation for those positions — have landed,
  // so it fits the camera to a stale/near-empty bbox and ends up far too
  // close once the real, spread-out layout appears moments later. Logging
  // showed getGraphBbox() holding at that stale value for 1-2 frames, then
  // jumping once to the real, stable bbox and holding it — so poll on rAF
  // until two consecutive reads agree (with a frame cap as a safety net)
  // before fitting, rather than fit on a fixed/guessed delay.
  //
  // EPOCH GUARD (Task 5 round 3): the poll spans multiple frames (up to
  // MAX_FRAMES/~1s). If nodes/edges change mid-poll, the [nodes, edges]
  // reset effect bumps pollEpochRef — this closure captured the epoch at
  // poll start, and every scheduled frame re-checks it before doing
  // anything else, so a stale poll from the old dataset bails out instead
  // of firing zoomToFit and clobbering the fresh poll's correct fit.
  //
  // REDUCED MOTION (final-review pass): this is a SYSTEM-initiated camera
  // fly, not a user gesture — under prefers-reduced-motion/test mode (the
  // exact paths that zero cooldownTicks specifically to eliminate motion),
  // an animated 400ms fly is itself a motion violation. Zero the duration
  // there so the fit is instant; only the real animated path (a live user
  // with no reduced-motion preference) gets the eased fly.
  const handleEngineStop = React.useCallback(() => {
    if (didFitRef.current) return;
    didFitRef.current = true;
    const epoch = pollEpochRef.current;
    const durationMs = reducedMotion || IS_TEST_MODE ? 0 : 400;
    let prevBboxKey: string | null = null;
    let frame = 0;
    const MAX_FRAMES = 60; // ~1s safety net at 60fps; settles in ~3 frames in practice
    const waitForStableBboxThenFit = () => {
      if (pollEpochRef.current !== epoch) return; // dataset changed mid-poll — stale, abandon
      frame += 1;
      const bbox = fgRef.current?.getGraphBbox();
      const key = bbox ? JSON.stringify(bbox) : null;
      if ((key !== null && key === prevBboxKey) || frame >= MAX_FRAMES) {
        fgRef.current?.zoomToFit(durationMs, 60);
        return;
      }
      prevBboxKey = key;
      pollRafIdRef.current = requestAnimationFrame(waitForStableBboxThenFit);
    };
    pollRafIdRef.current = requestAnimationFrame(waitForStableBboxThenFit);
  }, [reducedMotion]);

  return (
    <div style={{ width, height, position: "relative" }}>
      <ForceGraph3D
        fgRef={fgRef}
        width={width}
        height={height}
        graphData={graphData}
        nodeId="id"
        nodeThreeObject={nodeThreeObject}
        linkColor={linkColor}
        linkOpacity={0.4}
        linkWidth={linkWidth}
        backgroundColor="rgba(0,0,0,0)"
        showNavInfo={false}
        // Mirrors KnowledgeGraph2D's reduced-motion/test-mode path exactly
        // (`sim.alpha(1).tick(200).alpha(0).stop()`): run the simulation to
        // a real settled layout SYNCHRONOUSLY via warmupTicks, then skip the
        // animated cooldown loop. Without warmupTicks, cooldownTicks={0}
        // alone skips ALL physics ticks (3d-force-graph's tickFrame trips
        // its stop condition on the very first animated tick, before ever
        // calling layout.tick()) — nodes stay at d3-force-3d's raw
        // pre-simulation initial positions, an overlapping cluster nothing
        // like the settled layout 2D achieves the same way.
        warmupTicks={reducedMotion || IS_TEST_MODE ? 200 : 0}
        cooldownTicks={reducedMotion || IS_TEST_MODE ? 0 : 120}
        enableNodeDrag={false}
        onNodeClick={handleNodeClick}
        onNodeHover={handleNodeHover}
        onEngineStop={handleEngineStop}
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
      <button
        type="button"
        data-testid="graph-zoom-reset"
        className="btn btn--ghost btn--sm"
        title="Reset view"
        aria-label="Reset view"
        onClick={() => fgRef.current?.zoomToFit(reducedMotion || IS_TEST_MODE ? 0 : 400, 60)}
        style={{
          position: "absolute",
          right: 12,
          bottom: 12,
          padding: "2px 8px",
          fontSize: 10,
          background: "var(--bg-panel)",
          border: "1px solid var(--border)",
          borderRadius: "var(--r-sm)",
          boxShadow: "var(--shadow-sm)",
          zIndex: 5,
        }}
      >
        ⟲
      </button>
    </div>
  );
}
