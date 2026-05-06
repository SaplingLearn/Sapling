"use client";

/**
 * KnowledgeGraph — 3D WebGL knowledge-graph visualisation.
 *
 * Drop-in replacement for the previous 645-line SVG/d3-force version.
 * Same prop surface so the call sites in `Tree.tsx`, `Learn.tsx`, and
 * `Dashboard.tsx` keep working unchanged.
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
 * Variants (`orb` / `constellation` / `organism`) and comparison rings
 * from the old SVG version are intentionally **not** ported in the
 * first pass. The prop signatures stay so callers don't break, but
 * those values are ignored — see TODOs near the bottom of the file
 * if you want to bring them back.
 */

import React from "react";
import dynamic from "next/dynamic";
import { hashSeed, type GraphEdge, type GraphNode } from "@/lib/data";

// `react-force-graph-3d`'s default export touches `document` at
// module evaluation, so it can't be SSR'd. ssr: false ensures the
// import only fires in the browser. The fallback renders nothing —
// callers already wrap us in their own skeleton on first paint.
const ForceGraph3D = dynamic(
  () => import("react-force-graph-3d").then((m) => m.default),
  { ssr: false, loading: () => null },
);

// ── Public prop surface ───────────────────────────────────────────
// The old SVG version exposed `variant`, `comparison`,
// `comparisonColor`, `comparisonLabel`, `pauseWhenOffscreen`. The 3D
// backend doesn't yet implement those treatments, so they're removed
// from the public API rather than silently ignored — callers that
// pass them will hit a TypeScript error and be steered to a follow-up
// issue rather than wondering why their UI is gone.

type Props = {
  nodes: GraphNode[];
  edges: GraphEdge[];
  width?: number;
  height?: number;
  highlightId?: string;
  onNodeClick?: (n: GraphNode) => void;
};

// ── Color helpers (copied verbatim from the old SVG version) ──────
//
// Deterministic per-node shade derived from the course color + node id.
// Keeps each course visually unified while giving every node its own
// tone, and produces identical output across pages because it depends
// only on the stable inputs (no per-screen overrides).

function hexToHsl(hex: string): { h: number; s: number; l: number } | null {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex.trim());
  if (!m) return null;
  const r = parseInt(m[1].slice(0, 2), 16) / 255;
  const g = parseInt(m[1].slice(2, 4), 16) / 255;
  const b = parseInt(m[1].slice(4, 6), 16) / 255;
  const max = Math.max(r, g, b),
    min = Math.min(r, g, b),
    l = (max + min) / 2;
  let h = 0,
    s = 0;
  if (max !== min) {
    const d = max - min;
    s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
    if (max === r) h = ((g - b) / d + (g < b ? 6 : 0)) * 60;
    else if (max === g) h = ((b - r) / d + 2) * 60;
    else h = ((r - g) / d + 4) * 60;
  }
  return { h, s: s * 100, l: l * 100 };
}

function hslToHex(h: number, s: number, l: number): string {
  const sN = s / 100;
  const lN = l / 100;
  const c = (1 - Math.abs(2 * lN - 1)) * sN;
  const x = c * (1 - Math.abs(((h / 60) % 2) - 1));
  const m = lN - c / 2;
  let r = 0,
    g = 0,
    b = 0;
  if (h < 60) [r, g, b] = [c, x, 0];
  else if (h < 120) [r, g, b] = [x, c, 0];
  else if (h < 180) [r, g, b] = [0, c, x];
  else if (h < 240) [r, g, b] = [0, x, c];
  else if (h < 300) [r, g, b] = [x, 0, c];
  else [r, g, b] = [c, 0, x];
  const to = (v: number) =>
    Math.round((v + m) * 255)
      .toString(16)
      .padStart(2, "0");
  return `#${to(r)}${to(g)}${to(b)}`;
}

// Brand sage in HSL — used as a final fallback when the input color
// isn't parseable hex (e.g. callers pass through `var(--c-sage)`,
// which Three.js can't resolve). Precomputed so the call site doesn't
// need a non-null assertion that would silently break if anyone
// changed FALLBACK to an unparseable value.
const FALLBACK_HSL = { h: 75, s: 26, l: 48 } as const;

function shadeFor(baseHex: string, nodeId: string): string {
  const hsl = hexToHsl(baseHex) ?? FALLBACK_HSL;
  const seed = hashSeed(nodeId);
  // Hue variance is intentionally narrow (±10°) so each course family
  // reads as a single color band — children clearly belong to their
  // parent course rather than drifting into a sibling's hue. Within-
  // family distinction comes from saturation/lightness instead.
  const dh = (seed % 21) - 10;
  const ds = ((seed >> 5) % 17) - 8;
  const dl = ((seed >> 10) % 25) - 12;
  const h = (hsl.h + dh + 360) % 360;
  const s = Math.max(20, Math.min(85, hsl.s + ds));
  const l = Math.max(28, Math.min(62, hsl.l + dl));
  // Return hex (#RRGGBB), not `hsl(...)`. Three.js's Color.setStyle
  // only accepts comma-separated `hsl(h, s%, l%)`, not the modern
  // space-separated form; mismatches silently render black. Hex is
  // unambiguous across consumers.
  return hslToHex(h, s, l);
}

// ── Component ──────────────────────────────────────────────────────

// `react-force-graph-3d` mutates each node object in place (sets `x`,
// `y`, `z`, `vx`, `vy`, `vz`, `__threeObj`, …). To avoid mutating the
// caller's GraphNode array we shallow-clone every node and link.
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

// Visually hidden style for the AT-only node list. The WebGL canvas is
// opaque to assistive tech, so we mirror nodes as focusable buttons
// that share the `onNodeClick` activation behavior.
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

export function KnowledgeGraph({
  nodes,
  edges,
  width = 800,
  height = 480,
  highlightId,
  onNodeClick,
}: Props) {
  // Honour the user's reduced-motion preference. When set, we cut
  // simulation cooldown to 0 ticks so the lib stops physics
  // immediately — the graph appears in its initial position with no
  // animation. Otherwise we keep the default 120-tick settle.
  //
  // Lazy initializer reads matchMedia synchronously on first paint so
  // reduced-motion users don't see a one-frame flash of physics
  // before the effect flips the value.
  //
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
    // `addEventListener` on MediaQueryList isn't supported in Safari <14.
    // Fall back to addListener — both keep working in modern browsers.
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

  // Memoise the per-node colour function so identity is stable across
  // renders — avoids `react-force-graph-3d` rebuilding all node
  // materials on every parent re-render.
  const nodeColor = React.useCallback(
    (raw: object) => {
      const n = raw as FG3DNode;
      // Highlight uses the brand --accent (#8a9a5b) so it pops on both
      // the cream light theme and the near-black dark theme. Pure white
      // disappears against the cream background.
      if (n.id === highlightId) return "#8a9a5b";
      return shadeFor(n.color || "#8a9a5b", n.id);
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
    if (n.is_subject_root) return 22;
    return 4 + (typeof n.mastery_score === "number" ? n.mastery_score : 0) * 6;
  }, []);

  // O(1) id lookup for the click handler — beats `nodes.find` per
  // click on graphs with hundreds of nodes.
  const nodesById = React.useMemo(() => {
    const m = new Map<string, GraphNode>();
    for (const n of nodes) m.set(n.id, n);
    return m;
  }, [nodes]);

  const handleNodeClick = React.useCallback(
    (raw: object) => {
      if (!onNodeClick) return;
      const n = raw as FG3DNode;
      // Whitelist the original GraphNode by id so library-injected
      // fields (vx/vy/vz, fx/fy/fz, __threeObj, ...) never leak to
      // callers. If the node disappeared from the prop between the
      // sim run and the click (very rare, but possible with prop
      // updates), drop the click rather than synthesise a partial
      // node from the lib's mutated copy.
      const original = nodesById.get(n.id);
      if (original) onNodeClick(original);
    },
    [onNodeClick, nodesById],
  );

  return (
    // WebGL canvas is opaque to AT. The sr-only list below mirrors
    // every node as a focusable button so keyboard + screen-reader
    // users can reach the same activation behavior `onNodeClick`
    // provides to mouse users.
    <div
      // Reserve the layout slot at the parent's chosen size so the
      // canvas mounts without a layout shift on first render.
      style={{ width, height, position: "relative" }}
    >
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
          // Stronger conceptual links render thicker so the eye can
          // follow prerequisite chains visually.
          return 0.4 + (link.strength || 0) * 0.6;
        }}
        backgroundColor="rgba(0,0,0,0)"
        showNavInfo={false}
        cooldownTicks={reducedMotion ? 0 : 120}
        enableNodeDrag={false}
        onNodeClick={handleNodeClick}
      />
      <ul style={SR_ONLY} aria-label="Knowledge graph nodes">
        {nodes.map((n) =>
          onNodeClick ? (
            // Interactive entry — keyboard + AT users get a real
            // activation that mirrors the mouse-click behavior.
            <li key={n.id}>
              <button type="button" onClick={() => onNodeClick(n)}>
                {n.name}
              </button>
            </li>
          ) : (
            // No handler from the parent → render as static text so
            // we don't surface a focusable control that does nothing
            // (a "dead control" wastes Tab stops and is worse for AT
            // than a passive list item).
            <li key={n.id}>{n.name}</li>
          ),
        )}
      </ul>
    </div>
  );
}
