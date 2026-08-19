"use client";

/**
 * KnowledgeGraph3D — 3D WebGL knowledge-graph visualisation.
 *
 * Backed by `react-force-graph-3d` (Three.js + WebGL). The library
 * handles physics, camera, and picking; we provide the data adapter
 * and custom node objects — a matte sphere + a hidden focus halo +
 * an always-visible SpriteText label per node, built by
 * `nodeThreeObject` and registered in a per-dataset visuals registry
 * that the hover/highlight focus pass mutates in place, so restyling
 * never rebuilds geometry.
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

// Every restylable part of one node's Three.js group.
type NodeVisual = {
  sphereMat: THREE.MeshLambertMaterial;
  label: SpriteText;
  halo: THREE.Mesh;
  baseColor: string;
};

// Everything whose lifetime is exactly one dataset: the arrays handed to the
// library, the visuals registry the library fills through nodeThreeObject,
// and the halo geometry+material every node in that dataset shares. A single
// useMemo produces all of it (see `epoch` below) so the parts can never
// disagree about which dataset they belong to.
type GraphEpoch = {
  graphData: { nodes: FG3DNode[]; links: FG3DLink[] };
  visuals: Map<string, NodeVisual>;
  haloGeometry: THREE.SphereGeometry;
  haloMaterial: THREE.MeshBasicMaterial;
};

/**
 * Is this node inside the current focus neighborhood? No hover → everything
 * is lit. Shared by the focus pass (restyling live objects) and by
 * nodeThreeObject (building fresh ones) so a node rebuilt while the pointer
 * is already resting on a neighbor cannot disagree with one that was merely
 * restyled.
 */
function isLitUnderFocus(
  id: string,
  hover: string | null,
  adjacency: Map<string, Set<string>>,
): boolean {
  if (!hover) return true;
  return id === hover || (adjacency.get(hover)?.has(id) ?? false);
}

/**
 * Write one node's focus state onto its existing materials. Pure mutation —
 * no geometry, no allocation. The single writer of the focus look, called
 * both from the focus pass and from nodeThreeObject immediately after it
 * builds a node, so a mid-hover rebuild lands fully styled instead of
 * half-applied.
 */
function applyVisualState(
  v: NodeVisual,
  lit: boolean,
  focused: boolean,
  dimColor: string,
): void {
  v.sphereMat.color.set(lit ? v.baseColor : dimColor);
  v.sphereMat.opacity = lit ? NODE_OPACITY : DIM_NODE_OPACITY;
  v.label.material.opacity = lit ? 1 : DIM_LABEL_OPACITY;
  v.halo.visible = focused;
}

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
  // highlightId is mirrored in an EFFECT, never in the render body.
  // Assigning `highlightRef.current` during render is a react-hooks/refs
  // violation with real teeth under React 19: a render React starts and
  // then discards would still have written, so the ref could describe a
  // tree that never committed. Ordering is safe by a wide margin —
  // react-kapsule pushes props into the kapsule during its own render, but
  // kapsule's digest is `debounce(fn, 1)` (kapsule.mjs), so the library
  // cannot call nodeThreeObject until a macrotask after every effect in
  // this commit has run. First mount is covered by the initializer above.
  React.useEffect(() => {
    highlightRef.current = highlightId;
  }, [highlightId]);

  const adjacency = React.useMemo(() => buildAdjacency(edges), [edges]);

  // ONE memo owns every object whose lifetime is this dataset.
  //
  // The visuals registry used to be a ref cleared inside this memo. That is
  // a render-phase ref mutation, and under React 19 concurrent rendering a
  // render that starts and is then thrown away still clears it — leaving
  // the COMMITTED tree holding an empty registry, with hover focus a silent
  // no-op until the next dataset change. Deriving the registry from the
  // memo removes the failure mode by construction: whichever render
  // commits, its nodeThreeObject and its focus pass close over the SAME
  // map, and its graphData/nodeThreeObject identities are fresh, so the
  // library rebuilds every node object and repopulates that map.
  //
  // The shared halo geometry/material belong here rather than at module
  // scope because three-forcegraph's node digest calls
  // nodeDataMapper.clear() whenever `nodeThreeObject`'s identity changes
  // (three-forcegraph.mjs:1129) — which is exactly when this memo
  // recomputes. Every node object built from epoch N is therefore
  // deallocated (its geometries and materials disposed) before any epoch
  // N+1 object exists, so no surviving object can be left pointing at a
  // disposed shared resource.
  const epoch = React.useMemo<GraphEpoch>(
    () => ({
      graphData: {
        nodes: nodes.map((n) => ({ ...n })),
        links: edges.map((e) => ({
          source: e.source,
          target: e.target,
          strength: e.strength,
        })),
      },
      visuals: new Map<string, NodeVisual>(),
      // A unit sphere scaled per node instead of a per-node
      // SphereGeometry + MeshBasicMaterial pair: at most two halos (the
      // hovered node and highlightId) are ever visible, so the per-node
      // version carried N-2 dead geometry/material pairs for the dataset's
      // whole lifetime and re-allocated all N on every refresh.
      haloGeometry: new THREE.SphereGeometry(1, 16, 16),
      haloMaterial: new THREE.MeshBasicMaterial({
        color: theme.accent,
        transparent: true,
        opacity: 0.28,
        depthWrite: false,
      }),
    }),
    [nodes, edges, theme],
  );

  // Reset the auto-fit once-guard whenever the dataset changes. Runs after
  // the render that produced the new epoch commits — well before the
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

  // hoverId lives in state ONLY to re-key linkColor below; the
  // node/label/halo restyle happens imperatively through epoch.visuals, and
  // linkWidth deliberately reads hoverRef instead so its identity never
  // changes (see the comment on linkWidth).
  const [hoverId, setHoverId] = React.useState<string | null>(null);

  const applyFocus = React.useCallback(
    (hover: string | null) => {
      hoverRef.current = hover;
      for (const [id, v] of epoch.visuals) {
        applyVisualState(
          v,
          isLitUnderFocus(id, hover, adjacency),
          id === hover || id === highlightRef.current,
          theme.dim,
        );
      }
    },
    [adjacency, epoch, theme],
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
  // tutor moves the discussed node while the user isn't hovering). Declared
  // AFTER the highlightRef mirror effect above, so it reads the fresh
  // value: effects in one component run in declaration order.
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
      // 16 segments matches the library's own nodeResolution default. 24
      // was 2.25x the triangles per node for a sphere this small on screen,
      // and the design spec never asked for the extra tessellation.
      group.add(new THREE.Mesh(new THREE.SphereGeometry(r, 16, 16), sphereMat));

      // Focus halo: slightly larger translucent accent sphere, hidden until
      // this node is hovered or is the persistent highlightId. Geometry and
      // material are the dataset-shared pair; only the scale is per node.
      const halo = new THREE.Mesh(epoch.haloGeometry, epoch.haloMaterial);
      halo.scale.setScalar(r * 1.4);
      group.add(halo);

      const spec = labelSpec(n);
      // Constructor args, not setters: every three-spritetext setter re-runs
      // _genCanvas (measure -> resize canvas -> repaint -> new
      // CanvasTexture), so `new SpriteText(name)` plus four setters
      // rasterised each label FIVE times and allocated five textures — paid
      // again for the whole graph on every dataset refresh. The
      // (text, textHeight, color) constructor folds three of the five into
      // the one rasterisation that has to happen anyway.
      const label = new SpriteText(n.name, spec.textHeight, theme.ink);
      label.fontWeight = spec.fontWeight;
      label.fontFace = '"JetBrains Mono", monospace';
      label.material.transparent = true;
      label.position.set(0, -(r + spec.textHeight + 1.5), 0);
      group.add(label);

      const visual: NodeVisual = { sphereMat, label, halo, baseColor: color };
      epoch.visuals.set(n.id, visual);
      // Apply the CURRENT focus state to the node we just built. Any
      // nodes/edges identity change makes the library rebuild every node
      // object (a tutor graph_update refreshing the Learn rail, a filter
      // change on /tree). If the pointer is still resting on a node at that
      // moment, a freshly built graph would otherwise render half-focused —
      // the hovered node keeps its halo but nothing dims — until the
      // pointer moved. The [applyFocus, highlightId] re-assert effect
      // cannot cover it: that runs at commit, a kapsule debounce tick
      // before the library gets here, when the registry is still empty.
      applyVisualState(
        visual,
        isLitUnderFocus(n.id, hoverRef.current, adjacency),
        n.id === hoverRef.current || n.id === highlightRef.current,
        theme.dim,
      );
      return group;
    },
    [theme, epoch, adjacency],
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
  // halo next to sage-colored lit edges). Same reasoning for the resting
  // and dimmed rgb, which used to inline --ink-400's rgb by hand, twice.
  const litLinkRgb = React.useMemo(() => hexToRgbTriplet(theme.accent), [theme]);
  const baseLinkRgb = React.useMemo(() => hexToRgbTriplet(theme.link), [theme]);

  const linkColor = React.useCallback(
    (l: object) => {
      const link = l as FG3DLink;
      if (!hoverId) return `rgba(${baseLinkRgb}, ${BASE_LINK_ALPHA})`;
      const lit = linkEndId(link.source) === hoverId || linkEndId(link.target) === hoverId;
      // Lit links take the theme accent; dimmed links fade to near-invisible
      // warm gray.
      return lit
        ? `rgba(${litLinkRgb}, ${LIT_LINK_ALPHA})`
        : `rgba(${baseLinkRgb}, ${DIM_LINK_ALPHA})`;
    },
    [hoverId, litLinkRgb, baseLinkRgb],
  );

  // STABLE IDENTITY, DELIBERATELY: this reads hoverRef, not the hoverId
  // state, and its dep array is empty.
  //
  // `linkWidth` is one of the three props three-forcegraph treats as
  // object-invalidating for links: `if (state._flushObjects ||
  // hasAnyPropChanged(['linkThreeObject', 'linkThreeObjectExtend',
  // 'linkWidth'])) state.linkDataMapper.clear();` (three-forcegraph.mjs
  // :1199). clear() is digest([]) — it scene.remove()s and _deallocate()s
  // every link object and then recreates all of them; and because our
  // widths are always non-zero, `useCylinder` is always true, so each link
  // is a CylinderGeometry mesh. A hoverId-keyed useCallback handed the
  // library a NEW function identity on every pointer enter AND leave, i.e.
  // a full teardown/rebuild of the whole link layer twice per hover on a
  // few-hundred-edge graph. The design spec asks for the opposite: "Hover
  // mechanics — no per-hover geometry rebuilds".
  //
  // Widths still track the hover: linkColor's own identity change already
  // triggers the link digest, and that digest's onUpdateObj re-reads
  // `widthAccessor(link)` for every link and swaps in the wider cylinder
  // geometry (three-forcegraph.mjs:1256) — all without clear().
  const linkWidth = React.useCallback((l: object) => {
    const link = l as FG3DLink;
    const base = 0.4 + (link.strength || 0) * 0.6;
    const hover = hoverRef.current;
    if (!hover) return base;
    const lit = linkEndId(link.source) === hover || linkEndId(link.target) === hover;
    return lit ? base + 0.6 : base;
  }, []);

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
        graphData={epoch.graphData}
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
