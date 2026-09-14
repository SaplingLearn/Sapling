"use client";
import React from "react";
import {
  forceSimulation,
  forceLink,
  forceManyBody,
  forceCenter,
  forceCollide,
  forceX,
  forceY,
  type Simulation,
  type SimulationNodeDatum,
  type SimulationLinkDatum,
} from "d3-force";
import { type GraphEdge, type GraphNode } from "@/lib/data";
import {
  GLOW,
  NODE_STROKE_OPACITY,
  edgeWidthFor,
  opacityFor,
  radiusFor,
  shadeFor,
  truncateLabel,
} from "@/lib/graph/nodeStyle";
import { IS_TEST_MODE, random } from "@/lib/testMode";

export type GraphVariant = "orb" | "constellation" | "organism";

type SimNode = SimulationNodeDatum & GraphNode;
type SimLink = SimulationLinkDatum<SimNode> & {
  strength: number;
  source: string | SimNode;
  target: string | SimNode;
};

export interface GraphComparisonEntry {
  /** Partner's concept name — must match the primary graph's node name for the ring to render. */
  name: string;
  /** Partner mastery 0–1. Drives the ring radius/opacity. */
  mastery_score: number;
  /** Partner display name (for the tooltip/legend). */
  partner_name?: string;
}

type Props = {
  nodes: GraphNode[];
  edges: GraphEdge[];
  width?: number;
  height?: number;
  variant?: GraphVariant;
  highlightId?: string;
  onNodeClick?: (n: GraphNode) => void;
  /** Pause simulation when graph is off-screen (default: true). */
  pauseWhenOffscreen?: boolean;
  /** Partner concept mastery, matched to this graph's nodes by name. Renders an outline ring per match. */
  comparison?: GraphComparisonEntry[] | null;
  /** Color for the comparison ring (defaults to a muted accent). */
  comparisonColor?: string;
  /** Label for the legend/tooltip — usually the partner's display name. */
  comparisonLabel?: string;
};

// The pure node-style layer (shade, radius, tier opacity, edge width, label
// truncation) lives in `lib/graph/nodeStyle` (#537). It was byte-duplicated
// here and in KnowledgeGraph3D; the quiz surfaces consume the same module, so
// a retune moves the tree and the quiz together.

type DragState =
  | { kind: "node"; nodeId: string; pointerId: number }
  | { kind: "pan"; pointerId: number; startX: number; startY: number; originTx: number; originTy: number }
  | null;

const MIN_ZOOM = 0.4;
const MAX_ZOOM = 3;

// Visually-hidden but screen-reader-available. Mirrors KnowledgeGraph3D so the
// pointer-only SVG graph still exposes its nodes as a navigable text list.
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

function KnowledgeGraph2DImpl({
  nodes,
  edges,
  width = 600,
  height = 480,
  variant = "organism",
  highlightId,
  onNodeClick,
  pauseWhenOffscreen = true,
  comparison = null,
  comparisonColor = "#8a7bc4",
  comparisonLabel,
}: Props) {
  const comparisonByName = React.useMemo(() => {
    const map = new Map<string, GraphComparisonEntry>();
    for (const entry of comparison || []) {
      map.set(entry.name.trim().toLowerCase(), entry);
    }
    return map;
  }, [comparison]);
  const svgRef = React.useRef<SVGSVGElement>(null);
  const simRef = React.useRef<Simulation<SimNode, SimLink> | null>(null);
  const simNodesRef = React.useRef<SimNode[]>([]);
  const simLinksRef = React.useRef<SimLink[]>([]);

  const [, forceRerender] = React.useReducer((x) => x + 1, 0);
  const [hovered, setHovered] = React.useState<GraphNode | null>(null);
  const [view, setView] = React.useState({ tx: 0, ty: 0, scale: 1 });
  const dragRef = React.useRef<DragState>(null);
  const movedRef = React.useRef(false);

  // Per-tick position updates bypass React entirely (#111): the tick handler
  // writes node-group transforms and edge endpoints straight onto these DOM
  // elements, so a simulation tick never re-renders the tree. React renders
  // stay reserved for structural changes (nodes/edges added or removed,
  // hover, selection, pan/zoom). Same idea for the tooltip: state only seeds
  // its position when it (re)opens — while it's showing, pointer moves
  // reposition it via direct style writes, so a bare pointer-move never
  // calls setState.
  const nodeElsRef = React.useRef(new Map<string, SVGGElement>());
  const edgeElsRef = React.useRef(new Map<number, SVGLineElement>());
  const tooltipRef = React.useRef<HTMLDivElement>(null);
  const [tooltipPos, setTooltipPos] = React.useState({ x: 0, y: 0 });

  // d3 mutates node x/y in place, so JSX renders (which read the same
  // objects) and these direct writes always agree on the latest positions.
  const applyPositions = React.useCallback(() => {
    // Lazy id→node map: the link force replaces string endpoints with node
    // objects on init, so this fallback almost never materialises.
    let byId: Map<string, SimNode> | null = null;
    const resolve = (end: string | SimNode): SimNode | undefined => {
      if (typeof end === "object") return end;
      if (!byId) byId = new Map(simNodesRef.current.map((n) => [n.id, n]));
      return byId.get(end);
    };
    for (const n of simNodesRef.current) {
      if (n.x == null || n.y == null) continue;
      const el = nodeElsRef.current.get(n.id);
      if (el) el.setAttribute("transform", `translate(${n.x}, ${n.y})`);
    }
    simLinksRef.current.forEach((l, i) => {
      const el = edgeElsRef.current.get(i);
      if (!el) return;
      const s = resolve(l.source);
      const t = resolve(l.target);
      if (!s || !t || s.x == null || s.y == null || t.x == null || t.y == null) return;
      el.setAttribute("x1", String(s.x));
      el.setAttribute("y1", String(s.y));
      el.setAttribute("x2", String(t.x));
      el.setAttribute("y2", String(t.y));
    });
  }, []);

  // Rebuild the simulation whenever the node/edge set fundamentally changes.
  // We diff by id so stable nodes keep their current x/y/vx/vy.
  const dataKey = React.useMemo(
    () => nodes.map((n) => n.id).join("|") + "::" + edges.map((e) => `${e.source}-${e.target}`).join("|"),
    [nodes, edges],
  );

  React.useEffect(() => {
    // Merge new node data into existing sim nodes to preserve motion state.
    const byId = new Map(simNodesRef.current.map((n) => [n.id, n]));
    const nextNodes: SimNode[] = nodes.map((n) => {
      const prev = byId.get(n.id);
      if (prev) {
        // Keep position + velocity; refresh mutable data fields (mastery, color).
        Object.assign(prev, n);
        return prev;
      }
      const hubSeed = n.is_subject_root ? 0 : random();
      return {
        ...n,
        x: width / 2 + (random() - 0.5) * 40,
        y: height / 2 + (random() - 0.5) * 40,
        vx: 0,
        vy: 0,
        index: undefined,
        // eslint-disable-next-line @typescript-eslint/no-unused-vars
        _hub: hubSeed,
      } as SimNode;
    });

    const nextIds = new Set(nextNodes.map((n) => n.id));
    const nextLinks: SimLink[] = edges
      .filter((e) => nextIds.has(e.source) && nextIds.has(e.target))
      .map((e) => ({ source: e.source, target: e.target, strength: e.strength }));

    simNodesRef.current = nextNodes;
    simLinksRef.current = nextLinks;

    if (!simRef.current) {
      simRef.current = forceSimulation<SimNode>(nextNodes).on("tick", applyPositions);
    } else {
      simRef.current.nodes(nextNodes);
    }

    const sim = simRef.current;
    sim
      .force(
        "link",
        forceLink<SimNode, SimLink>(nextLinks)
          .id((d) => d.id)
          .distance((l) => 40 + (1 - (l.strength || 0.5)) * 90)
          .strength((l) => 0.15 + (l.strength || 0.5) * 0.4),
      )
      .force("charge", forceManyBody<SimNode>().strength((d) => (d.is_subject_root ? -400 : -120)))
      .force(
        "collide",
        forceCollide<SimNode>().radius((d) => (d.is_subject_root ? 36 : 18 + (d.mastery_score || 0) * 6)),
      )
      .force("center", forceCenter(width / 2, height / 2).strength(0.06))
      .force("x", forceX<SimNode>(width / 2).strength(0.02))
      .force("y", forceY<SimNode>(height / 2).strength(0.02));

    // Test mode rides the reduced-motion path: the simulation settles
    // synchronously (fixed tick count) instead of animating on rAF, so
    // node coordinates are identical on every load.
    const reducedMotion = IS_TEST_MODE
      || (typeof window !== "undefined"
        && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches);
    if (reducedMotion) {
      sim.alpha(1).tick(200).alpha(0).stop();
    } else {
      sim.alpha(0.9).restart();
    }
    // One structural render mounts the node/edge elements at their current
    // coordinates; from here on ticks write positions straight to the DOM.
    forceRerender();

    return () => {
      // Simulation is kept across renders; only stop on full unmount below.
    };
  }, [dataKey, width, height]);

  // Stop the simulation on unmount.
  React.useEffect(() => {
    return () => {
      simRef.current?.stop();
      simRef.current = null;
    };
  }, []);

  // ── Helpers ──────────────────────────────────────────────────────────────
  const nodeRadius = (n: GraphNode) => radiusFor(n.mastery_score, n.is_subject_root);
  const courseColor = (n?: GraphNode) => {
    if (!n) return "var(--c-sage)";
    const base = n.color || "var(--c-sage)";
    if (n.is_subject_root) return base;
    return shadeFor(base, n.id);
  };
  const fillFor = (n: GraphNode) => courseColor(n);

  // ── Pause simulation when offscreen ─────────────────────────────────────
  React.useEffect(() => {
    if (!pauseWhenOffscreen) return;
    const el = svgRef.current;
    if (!el || typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver(
      entries => {
        for (const entry of entries) {
          const sim = simRef.current;
          if (!sim) continue;
          if (entry.isIntersecting) {
            sim.alphaTarget(0).restart();
          } else {
            sim.stop();
          }
        }
      },
      { threshold: 0.01 },
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, [pauseWhenOffscreen]);

  const subjectAverage = React.useMemo(() => {
    const map: Record<string, { total: number; count: number }> = {};
    for (const n of nodes) {
      if (n.is_subject_root) continue;
      const key = n.subject;
      if (!map[key]) map[key] = { total: 0, count: 0 };
      map[key].total += n.mastery_score || 0;
      map[key].count += 1;
    }
    const result: Record<string, number> = {};
    for (const s in map) result[s] = map[s].count ? map[s].total / map[s].count : 0;
    return result;
  }, [nodes]);

  // Constrain the pan/zoom transform so the graph can't be dragged off into
  // empty space: the content's bounding box stays inside the window, or — when
  // it's larger than the window — always covers it. Applied on pan and zoom.
  const clampView = (tx: number, ty: number, scale: number) => {
    const ns = simNodesRef.current;
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    for (const n of ns) {
      if (n.x == null || n.y == null) continue;
      const r = nodeRadius(n) + 24; // node radius + label/glow allowance
      if (n.x - r < minX) minX = n.x - r;
      if (n.x + r > maxX) maxX = n.x + r;
      if (n.y - r < minY) minY = n.y - r;
      if (n.y + r > maxY) maxY = n.y + r;
    }
    if (!Number.isFinite(minX)) return { tx, ty };
    const clamp = (v: number, a: number, b: number) => {
      const lo = Math.min(a, b), hi = Math.max(a, b);
      return Math.max(lo, Math.min(hi, v));
    };
    return {
      tx: clamp(tx, -minX * scale, width - maxX * scale),
      ty: clamp(ty, -minY * scale, height - maxY * scale),
    };
  };

  // ── Pointer interaction ─────────────────────────────────────────────────
  const clientToSvg = (clientX: number, clientY: number) => {
    const svg = svgRef.current;
    if (!svg) return { x: 0, y: 0 };
    const rect = svg.getBoundingClientRect();
    return {
      x: (clientX - rect.left - view.tx) / view.scale,
      y: (clientY - rect.top - view.ty) / view.scale,
    };
  };

  const onNodePointerDown = (e: React.PointerEvent, n: SimNode) => {
    e.stopPropagation();
    (e.currentTarget as Element).setPointerCapture(e.pointerId);
    dragRef.current = { kind: "node", nodeId: n.id, pointerId: e.pointerId };
    movedRef.current = false;
    simRef.current?.alphaTarget(0.3).restart();
    n.fx = n.x;
    n.fy = n.y;
    // dragRef/fx are refs — render once so the tooltip hides and the pinned
    // stroke shows (ticks no longer re-render on our behalf).
    forceRerender();
  };

  const onSvgPointerDown = (e: React.PointerEvent) => {
    if (e.button !== 0) return;
    const svg = svgRef.current;
    if (!svg) return;
    svg.setPointerCapture(e.pointerId);
    dragRef.current = {
      kind: "pan",
      pointerId: e.pointerId,
      startX: e.clientX,
      startY: e.clientY,
      originTx: view.tx,
      originTy: view.ty,
    };
    movedRef.current = false;
    svg.style.cursor = "grabbing"; // direct write; restored on pointer-up
  };

  const onPointerMove = (e: React.PointerEvent) => {
    // Reposition the tooltip only while it's actually mounted, and via a
    // direct style write — no setState on a bare pointer-move.
    const tip = tooltipRef.current;
    if (tip) {
      tip.style.left = `${e.clientX + 14}px`;
      tip.style.top = `${e.clientY + 14}px`;
    }
    const drag = dragRef.current;
    if (!drag || e.pointerId !== drag.pointerId) return;
    movedRef.current = true;
    if (drag.kind === "node") {
      const n = simNodesRef.current.find((sn) => sn.id === drag.nodeId);
      if (!n) return;
      const { x, y } = clientToSvg(e.clientX, e.clientY);
      // Keep the dragged node inside the window: map the visible bounds back
      // into content coords through the current view transform.
      const r = nodeRadius(n);
      const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v));
      n.fx = clamp(x, (r - view.tx) / view.scale, (width - r - view.tx) / view.scale);
      n.fy = clamp(y, (r - view.ty) / view.scale, (height - r - view.ty) / view.scale);
    } else if (drag.kind === "pan") {
      const dx = e.clientX - drag.startX;
      const dy = e.clientY - drag.startY;
      setView((v) => {
        const c = clampView(drag.originTx + dx, drag.originTy + dy, v.scale);
        return { ...v, tx: c.tx, ty: c.ty };
      });
    }
  };

  const onPointerUp = (e: React.PointerEvent) => {
    const drag = dragRef.current;
    if (!drag) return;
    dragRef.current = null;
    try {
      (e.currentTarget as Element).releasePointerCapture(e.pointerId);
    } catch {}
    if (drag.kind === "node") {
      const n = simNodesRef.current.find((sn) => sn.id === drag.nodeId);
      if (n) {
        // Release the pin so the simulation takes over again.
        n.fx = null;
        n.fy = null;
      }
      simRef.current?.alphaTarget(0);
    }
    if (svgRef.current) svgRef.current.style.cursor = "grab";
    // Restore tooltip/stroke now that dragRef cleared; reseed the tooltip
    // position so it remounts under the release point, not where the hover
    // started.
    setTooltipPos({ x: e.clientX, y: e.clientY });
    forceRerender();
  };

  const onWheel = (e: React.WheelEvent) => {
    if (!svgRef.current) return;
    const rect = svgRef.current.getBoundingClientRect();
    const mx = e.clientX - rect.left;
    const my = e.clientY - rect.top;
    const delta = -e.deltaY * 0.0015;
    setView((v) => {
      const nextScale = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, v.scale * (1 + delta)));
      const factor = nextScale / v.scale;
      const c = clampView(mx - (mx - v.tx) * factor, my - (my - v.ty) * factor, nextScale);
      return { tx: c.tx, ty: c.ty, scale: nextScale };
    });
  };

  const resetView = () => setView({ tx: 0, ty: 0, scale: 1 });

  const hoveredMastery = hovered
    ? hovered.is_subject_root
      ? subjectAverage[hovered.subject] ?? 0
      : hovered.mastery_score || 0
    : 0;

  const simNodes = simNodesRef.current;
  const simLinks = simLinksRef.current;
  // O(1) endpoint resolution for edges whose source/target is still an id
  // string (before the link force swaps in node objects) — replaces the old
  // per-edge .find() over all nodes.
  const nodeById = new Map<string, SimNode>();
  for (const n of simNodes) nodeById.set(n.id, n);

  return (
    <div style={{ position: "relative", width, height, overflow: "hidden", background: "transparent" }}>
      <svg
        ref={svgRef}
        width={width}
        height={height}
        role="img"
        aria-label="Knowledge graph"
        style={{
          display: "block",
          cursor: "grab",
          touchAction: "none",
        }}
        onPointerDown={onSvgPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
        onWheel={onWheel}
      >
        <defs>
          <filter id="soft">
            <feGaussianBlur stdDeviation={GLOW.blur} />
          </filter>
        </defs>

        <g transform={`translate(${view.tx}, ${view.ty}) scale(${view.scale})`}>
          {/* Edges */}
          <g>
            {simLinks.map((l, i) => {
              const s = typeof l.source === "object" ? (l.source as SimNode) : nodeById.get(String(l.source));
              const t = typeof l.target === "object" ? (l.target as SimNode) : nodeById.get(String(l.target));
              if (!s || !t || s.x == null || t.x == null) return null;
              const op = variant === "constellation" ? 0.35 : 0.2;
              return (
                <line
                  key={i}
                  ref={(el) => {
                    if (el) edgeElsRef.current.set(i, el);
                    else edgeElsRef.current.delete(i);
                  }}
                  data-testid="graph-edge"
                  x1={s.x}
                  y1={s.y}
                  x2={t.x}
                  y2={t.y}
                  stroke="var(--text-muted)"
                  strokeOpacity={op}
                  strokeWidth={edgeWidthFor(l.strength)}
                  strokeLinecap="round"
                />
              );
            })}
          </g>

          {/* Nodes */}
          <g>
            {simNodes.map((n) => {
              if (n.x == null || n.y == null) return null;
              const r = nodeRadius(n);
              const color = fillFor(n);
              const op = n.is_subject_root ? 1 : opacityFor(n.mastery_tier);
              const isHl = highlightId === n.id;
              const isHovered = hovered?.id === n.id;
              const isPinned = n.fx != null && n.fy != null;
              return (
                <g
                  key={n.id}
                  ref={(el) => {
                    if (el) nodeElsRef.current.set(n.id, el);
                    else nodeElsRef.current.delete(n.id);
                  }}
                  data-testid="graph-node"
                  data-node-id={n.id}
                  transform={`translate(${n.x}, ${n.y})`}
                  style={{ cursor: "grab" }}
                  onPointerDown={(ev) => onNodePointerDown(ev, n)}
                  onPointerEnter={(ev) => {
                    // Seed the tooltip position as it mounts so it opens
                    // under the cursor, not at a stale spot.
                    setTooltipPos({ x: ev.clientX, y: ev.clientY });
                    setHovered(n);
                  }}
                  onPointerLeave={() => setHovered((h) => (h?.id === n.id ? null : h))}
                  onClick={(ev) => {
                    ev.stopPropagation();
                    if (movedRef.current) return;
                    onNodeClick?.(n);
                  }}
                >
                  {variant === "organism" && (
                    <circle cx={0} cy={0} r={r + GLOW.pad} fill={color} opacity={GLOW.opacity} filter="url(#soft)" />
                  )}
                  {isHl && (
                    <circle cx={0} cy={0} r={r + 7} fill="none" stroke={color} strokeWidth={2} opacity={0.7}>
                      <animate
                        attributeName="r"
                        values={`${r + 5};${r + 11};${r + 5}`}
                        dur="2.4s"
                        repeatCount="indefinite"
                      />
                    </circle>
                  )}
                  {(() => {
                    const partner = !n.is_subject_root && comparisonByName.get((n.name || "").trim().toLowerCase());
                    if (!partner) return null;
                    const partnerR = r + 4 + partner.mastery_score * 5;
                    return (
                      <circle
                        cx={0}
                        cy={0}
                        r={partnerR}
                        fill="none"
                        stroke={comparisonColor}
                        strokeWidth={1.8}
                        strokeDasharray="3 3"
                        opacity={0.35 + partner.mastery_score * 0.55}
                      >
                        <title>
                          {comparisonLabel ? `${comparisonLabel}: ` : ""}
                          {Math.round(partner.mastery_score * 100)}% mastery on {n.name}
                        </title>
                      </circle>
                    );
                  })()}
                  {variant === "constellation" ? (
                    <>
                      <circle data-testid="graph-node-circle" cx={0} cy={0} r={r * 0.7} fill={color} opacity={op} />
                      <circle cx={0} cy={0} r={r * 1.6} fill="none" stroke={color} strokeWidth={0.5} opacity={op * 0.4} />
                    </>
                  ) : (
                    <circle
                      data-testid="graph-node-circle"
                      cx={0}
                      cy={0}
                      r={r}
                      fill={color}
                      opacity={op}
                      stroke={color}
                      strokeWidth={n.is_subject_root ? 2.5 : 1.5}
                      strokeOpacity={isPinned ? 1 : isHovered ? 0.9 : NODE_STROKE_OPACITY}
                    />
                  )}
                  {n.is_subject_root && (
                    <text
                      x={0}
                      y={r + 16}
                      textAnchor="middle"
                      fontFamily="var(--font-display)"
                      fontSize={13}
                      fontWeight={600}
                      fill={color}
                      pointerEvents="none"
                    >
                      {n.name}
                    </text>
                  )}
                  {!n.is_subject_root && (
                    <text
                      x={0}
                      y={r + 13}
                      textAnchor="middle"
                      fontFamily="var(--font-sans)"
                      fontSize={10.5}
                      fill="var(--text-dim)"
                      opacity={0.85}
                      pointerEvents="none"
                    >
                      {truncateLabel(n.name)}
                    </text>
                  )}
                </g>
              );
            })}
          </g>
        </g>
      </svg>

      <div
        style={{
          position: "absolute",
          top: 12,
          right: 12,
          display: "flex",
          flexDirection: "column",
          gap: 4,
          background: "var(--bg-panel)",
          border: "1px solid var(--border)",
          borderRadius: "var(--r-sm)",
          padding: 4,
          boxShadow: "var(--shadow-sm)",
        }}
      >
        <button
          data-testid="graph-zoom-in"
          className="btn btn--ghost btn--sm"
          style={{ padding: "2px 8px", fontFamily: "var(--font-mono)" }}
          onClick={() => setView((v) => {
            const s = Math.min(MAX_ZOOM, v.scale * 1.2);
            const c = clampView(v.tx, v.ty, s);
            return { tx: c.tx, ty: c.ty, scale: s };
          })}
          title="Zoom in"
        >
          +
        </button>
        <button
          data-testid="graph-zoom-out"
          className="btn btn--ghost btn--sm"
          style={{ padding: "2px 8px", fontFamily: "var(--font-mono)" }}
          onClick={() => setView((v) => {
            const s = Math.max(MIN_ZOOM, v.scale / 1.2);
            const c = clampView(v.tx, v.ty, s);
            return { tx: c.tx, ty: c.ty, scale: s };
          })}
          title="Zoom out"
        >
          −
        </button>
        <button
          data-testid="graph-zoom-reset"
          className="btn btn--ghost btn--sm"
          style={{ padding: "2px 8px", fontSize: 10 }}
          onClick={resetView}
          title="Reset view"
        >
          ⟲
        </button>
      </div>

      {hovered && !dragRef.current && (
        <div
          ref={tooltipRef}
          style={{
            position: "fixed",
            left: tooltipPos.x + 14,
            top: tooltipPos.y + 14,
            background: "var(--bg-panel)",
            border: "1px solid var(--border-strong)",
            borderRadius: "var(--r-md)",
            padding: "10px 12px",
            boxShadow: "var(--shadow-md)",
            pointerEvents: "none",
            zIndex: 50,
            fontSize: 12,
            minWidth: 200,
          }}
        >
          <div style={{ fontFamily: "var(--font-display)", fontSize: 14, marginBottom: 4 }}>{hovered.name}</div>
          <div style={{ display: "flex", alignItems: "center", gap: 6, color: "var(--text-dim)" }}>
            <span style={{ width: 8, height: 8, borderRadius: "50%", background: courseColor(hovered) }} />
            {hovered.is_subject_root ? "Course" : hovered.subject}
          </div>
          <div style={{ marginTop: 8 }}>
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                fontSize: 11,
                color: "var(--text-muted)",
                marginBottom: 4,
              }}
            >
              <span>{hovered.is_subject_root ? "Avg. mastery" : "Mastery"}</span>
              <span className="mono" style={{ color: "var(--text)" }}>
                {Math.round(hoveredMastery * 100)}%
              </span>
            </div>
            <div
              style={{
                height: 4,
                background: "var(--bg-soft)",
                borderRadius: "var(--r-full)",
                overflow: "hidden",
              }}
            >
              <div
                style={{
                  width: "100%",
                  height: "100%",
                  background: courseColor(hovered),
                  transformOrigin: "left",
                  transform: `scaleX(${hoveredMastery})`,
                  transition: "transform var(--dur) var(--ease)",
                }}
              />
            </div>
          </div>
          {!hovered.is_subject_root && (
            <div style={{ marginTop: 6, color: "var(--text-dim)", fontSize: 11, textTransform: "capitalize" }}>
              {hovered.mastery_tier}
              {hovered.last_studied_at && <> · {hovered.last_studied_at}</>}
            </div>
          )}
        </div>
      )}
      {/* The a11y node list doubles as the browser suite's data seam (#395):
          `graph-node-item` mirrors the `nodes` prop 1:1 and carries the node
          id as `data-node-id` so tests assert by identity, never by label
          (concept names are only unique per course). Registered in
          docs/frontend-testids.md. */}
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

export const KnowledgeGraph2D = React.memo(KnowledgeGraph2DImpl);
