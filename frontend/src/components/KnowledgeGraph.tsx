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
import type { GraphEdge, GraphNode } from "@/lib/data";

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

// Deterministic per-node shade derived from the course color + node id.
// Keeps each course visually unified while giving every node its own tone,
// and produces identical output across pages because it depends only on the
// stable inputs (no per-screen overrides).
function hashId(id: string): number {
  let h = 0;
  for (let i = 0; i < id.length; i++) h = ((h << 5) - h + id.charCodeAt(i)) | 0;
  return Math.abs(h);
}

function hexToHsl(hex: string): { h: number; s: number; l: number } | null {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex.trim());
  if (!m) return null;
  const r = parseInt(m[1].slice(0, 2), 16) / 255;
  const g = parseInt(m[1].slice(2, 4), 16) / 255;
  const b = parseInt(m[1].slice(4, 6), 16) / 255;
  const max = Math.max(r, g, b), min = Math.min(r, g, b), l = (max + min) / 2;
  let h = 0, s = 0;
  if (max !== min) {
    const d = max - min;
    s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
    if (max === r) h = ((g - b) / d + (g < b ? 6 : 0)) * 60;
    else if (max === g) h = ((b - r) / d + 2) * 60;
    else h = ((r - g) / d + 4) * 60;
  }
  return { h, s: s * 100, l: l * 100 };
}

function shadeFor(baseHex: string, nodeId: string): string {
  const hsl = hexToHsl(baseHex);
  if (!hsl) return baseHex;
  const seed = hashId(nodeId);
  const dh = (seed % 51) - 25;
  const ds = ((seed >> 5) % 17) - 8;
  const dl = ((seed >> 10) % 25) - 12;
  const h = (hsl.h + dh + 360) % 360;
  const s = Math.max(20, Math.min(85, hsl.s + ds));
  const l = Math.max(28, Math.min(62, hsl.l + dl));
  return `hsl(${h.toFixed(0)} ${s.toFixed(0)}% ${l.toFixed(0)}%)`;
}

type DragState =
  | { kind: "node"; nodeId: string; pointerId: number }
  | { kind: "pan"; pointerId: number; startX: number; startY: number; originTx: number; originTy: number }
  | null;

const MIN_ZOOM = 0.4;
const MAX_ZOOM = 3;

function KnowledgeGraphImpl({
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
  const [tooltipPos, setTooltipPos] = React.useState({ x: 0, y: 0 });
  const [view, setView] = React.useState({ tx: 0, ty: 0, scale: 1 });
  const dragRef = React.useRef<DragState>(null);
  const movedRef = React.useRef(false);

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
      const hubSeed = n.is_subject_root ? 0 : Math.random();
      return {
        ...n,
        x: width / 2 + (Math.random() - 0.5) * 40,
        y: height / 2 + (Math.random() - 0.5) * 40,
        vx: 0,
        vy: 0,
        index: undefined,
        // eslint-disable-next-line @typescript-eslint/no-unused-vars
        _hub: hubSeed,
      } as SimNode;
    });

    const nextLinks: SimLink[] = edges
      .filter((e) => nextNodes.some((n) => n.id === e.source) && nextNodes.some((n) => n.id === e.target))
      .map((e) => ({ source: e.source, target: e.target, strength: e.strength }));

    simNodesRef.current = nextNodes;
    simLinksRef.current = nextLinks;

    if (!simRef.current) {
      simRef.current = forceSimulation<SimNode>(nextNodes).on("tick", () => {
        forceRerender();
      });
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

    const reducedMotion = typeof window !== "undefined"
      && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    if (reducedMotion) {
      sim.alpha(1).tick(200).alpha(0).stop();
      forceRerender();
    } else {
      sim.alpha(0.9).restart();
    }

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
  const masteryOpacity = (tier: GraphNode["mastery_tier"]) =>
    ({ mastered: 1, learning: 0.78, struggling: 0.55, unexplored: 0.28 })[tier] || 0.6;
  const nodeRadius = (n: GraphNode) => (n.is_subject_root ? 22 : 8 + (n.mastery_score || 0) * 12);
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
  };

  const onPointerMove = (e: React.PointerEvent) => {
    setTooltipPos({ x: e.clientX, y: e.clientY });
    const drag = dragRef.current;
    if (!drag || e.pointerId !== drag.pointerId) return;
    movedRef.current = true;
    if (drag.kind === "node") {
      const n = simNodesRef.current.find((sn) => sn.id === drag.nodeId);
      if (!n) return;
      const { x, y } = clientToSvg(e.clientX, e.clientY);
      n.fx = x;
      n.fy = y;
    } else if (drag.kind === "pan") {
      const dx = e.clientX - drag.startX;
      const dy = e.clientY - drag.startY;
      setView((v) => ({ ...v, tx: drag.originTx + dx, ty: drag.originTy + dy }));
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
      return {
        tx: mx - (mx - v.tx) * factor,
        ty: my - (my - v.ty) * factor,
        scale: nextScale,
      };
    });
  };

  const resetView = () => setView({ tx: 0, ty: 0, scale: 1 });
  const reheat = () => simRef.current?.alpha(0.8).restart();

  const hoveredMastery = hovered
    ? hovered.is_subject_root
      ? subjectAverage[hovered.subject] ?? 0
      : hovered.mastery_score || 0
    : 0;

  const simNodes = simNodesRef.current;
  const simLinks = simLinksRef.current;

  return (
    <div style={{ position: "relative", width, height, overflow: "hidden", background: "transparent" }}>
      <svg
        ref={svgRef}
        width={width}
        height={height}
        style={{
          display: "block",
          cursor: dragRef.current?.kind === "pan" ? "grabbing" : "grab",
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
            <feGaussianBlur stdDeviation="3" />
          </filter>
        </defs>

        <g transform={`translate(${view.tx}, ${view.ty}) scale(${view.scale})`}>
          {/* Edges */}
          <g>
            {simLinks.map((l, i) => {
              const s = typeof l.source === "object" ? (l.source as SimNode) : simNodes.find((n) => n.id === l.source);
              const t = typeof l.target === "object" ? (l.target as SimNode) : simNodes.find((n) => n.id === l.target);
              if (!s || !t || s.x == null || t.x == null) return null;
              const op = variant === "constellation" ? 0.35 : 0.2;
              return (
                <line
                  key={i}
                  x1={s.x}
                  y1={s.y}
                  x2={t.x}
                  y2={t.y}
                  stroke="var(--text-muted)"
                  strokeOpacity={op}
                  strokeWidth={0.5 + (l.strength || 0.5) * 1.2}
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
              const op = n.is_subject_root ? 1 : masteryOpacity(n.mastery_tier);
              const isHl = highlightId === n.id;
              const isHovered = hovered?.id === n.id;
              const isPinned = n.fx != null && n.fy != null;
              return (
                <g
                  key={n.id}
                  style={{ cursor: "grab" }}
                  onPointerDown={(ev) => onNodePointerDown(ev, n)}
                  onPointerEnter={() => setHovered(n)}
                  onPointerLeave={() => setHovered((h) => (h?.id === n.id ? null : h))}
                  onClick={(ev) => {
                    ev.stopPropagation();
                    if (movedRef.current) return;
                    onNodeClick?.(n);
                  }}
                >
                  {variant === "organism" && (
                    <circle cx={n.x} cy={n.y} r={r + 8} fill={color} opacity={0.15} filter="url(#soft)" />
                  )}
                  {isHl && (
                    <circle cx={n.x} cy={n.y} r={r + 7} fill="none" stroke={color} strokeWidth={2} opacity={0.7}>
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
                        cx={n.x}
                        cy={n.y}
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
                      <circle cx={n.x} cy={n.y} r={r * 0.7} fill={color} opacity={op} />
                      <circle cx={n.x} cy={n.y} r={r * 1.6} fill="none" stroke={color} strokeWidth={0.5} opacity={op * 0.4} />
                    </>
                  ) : (
                    <circle
                      cx={n.x}
                      cy={n.y}
                      r={r}
                      fill={color}
                      opacity={op}
                      stroke={color}
                      strokeWidth={n.is_subject_root ? 2.5 : 1.5}
                      strokeOpacity={isPinned ? 1 : isHovered ? 0.9 : 0.4}
                    />
                  )}
                  {n.is_subject_root && (
                    <text
                      x={n.x}
                      y={n.y + r + 16}
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
                  {!n.is_subject_root && r > 10 && (
                    <text
                      x={n.x}
                      y={n.y + r + 13}
                      textAnchor="middle"
                      fontFamily="var(--font-sans)"
                      fontSize={10.5}
                      fill="var(--text-dim)"
                      opacity={0.85}
                      pointerEvents="none"
                    >
                      {n.name.length > 18 ? n.name.slice(0, 17) + "…" : n.name}
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
          className="btn btn--ghost btn--sm"
          style={{ padding: "2px 8px", fontFamily: "var(--font-mono)" }}
          onClick={() => setView((v) => ({ ...v, scale: Math.min(MAX_ZOOM, v.scale * 1.2) }))}
          title="Zoom in"
        >
          +
        </button>
        <button
          className="btn btn--ghost btn--sm"
          style={{ padding: "2px 8px", fontFamily: "var(--font-mono)" }}
          onClick={() => setView((v) => ({ ...v, scale: Math.max(MIN_ZOOM, v.scale / 1.2) }))}
          title="Zoom out"
        >
          −
        </button>
        <button
          className="btn btn--ghost btn--sm"
          style={{ padding: "2px 8px", fontSize: 10 }}
          onClick={resetView}
          title="Reset view"
        >
          ⟲
        </button>
        <button
          className="btn btn--ghost btn--sm"
          style={{ padding: "2px 8px", fontSize: 10 }}
          onClick={reheat}
          title="Re-run forces"
        >
          ✦
        </button>
      </div>

      {hovered && !dragRef.current && (
        <div
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
    </div>
  );
}

export const KnowledgeGraph = React.memo(KnowledgeGraphImpl);
