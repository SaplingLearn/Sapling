"use client";
import React from "react";
import {
  forceSimulation,
  forceLink,
  forceManyBody,
  forceCollide,
  type Simulation,
  type SimulationNodeDatum,
  type SimulationLinkDatum,
} from "d3-force";
import { type GraphEdge, type GraphNode } from "@/lib/data";
import {
  GLOW,
  NODE_STROKE_OPACITY,
  edgeWidthFor,
  masteryFillFor,
  opacityFor,
  radiusFor,
  shadeFor,
  truncateLabel,
  type GraphColorMode,
} from "@/lib/graph/nodeStyle";
import { IS_TEST_MODE } from "@/lib/testMode";
import {
  courseLinks,
  forceOrbit,
  importanceRadii,
  isDirected,
  labelOpacityAt,
  planBounds,
  planRadial,
  splitEdges,
  type RadialPlan,
} from "@/lib/graph/radialLayout";

export type GraphVariant = "orb" | "constellation" | "organism";

type SimNode = SimulationNodeDatum & GraphNode;
type SimLink = SimulationLinkDatum<SimNode> & {
  strength: number;
  relationship_type?: GraphEdge["relationship_type"];
  /** A course → inner-circle link: drawn, but the orbit force places it. */
  anchor?: boolean;
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
  /**
   * The zoom the graph opens (and resets) at, centred on the window. Default
   * 1. A small fragment (quiz home's neighbourhood) settles to a cluster far
   * smaller than its window; this lets it fill the frame without changing the
   * simulation's spacing, which the full tree depends on.
   */
  initialZoom?: number;
  /** `course` (default): course colours, tier as opacity. `mastery`: one
   *  colour per mastery tier, hubs brown, edges blend between their ends. */
  colorMode?: GraphColorMode;
  /** Top offset of the zoom stack (default 12, flush with the corner). */
  zoomControlsTop?: number;
  /**
   * Obsidian-style legibility (preview only for now): hovering a concept
   * fades everything but it and its neighbours, concept labels fade in with
   * zoom, nodes size by how many concepts build on them, and links stay quiet
   * with direction arrows when zoomed in or focused.
   */
  legible?: boolean;
  /** Legible: fade every course but this one (a hovered "My courses" row). */
  focusCourseId?: string | null;
  /** Legible: the course of the concept under the pointer, or null on leave. */
  onHoverCourse?: (courseId: string | null) => void;
  /** Legible: zoom to a course; a new `seq` asks again for the same course. */
  zoomRequest?: { courseId: string; seq: number } | null;
};

// The pure node-style layer (shade, radius, tier opacity, edge width, label
// truncation, colour modes) lives in `lib/graph/nodeStyle` (#537); the quiz
// surfaces consume the same module, so a retune moves the tree and the quiz
// together.

type DragState =
  | { kind: "node"; nodeId: string; pointerId: number }
  | { kind: "pan"; pointerId: number; startX: number; startY: number; originTx: number; originTy: number }
  | null;

const MIN_ZOOM = 0.4;
/** Smallest on-screen node radius (px) in legible mode. */
const MIN_SCREEN_R = 7;

/** Where a line from (x1, y1) to (x2, y2) should stop to end `inset` short. */
function lineEnd(x1: number, y1: number, x2: number, y2: number, inset: number): [number, number] {
  const dx = x2 - x1;
  const dy = y2 - y1;
  const len = Math.hypot(dx, dy);
  if (len <= inset * 1.5) return [x2, y2];
  return [x2 - (dx / len) * inset, y2 - (dy / len) * inset];
}
const MAX_ZOOM = 3;

// Visually-hidden but screen-reader-available, so the pointer-only SVG graph
// still exposes its nodes as a navigable text list.
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
  initialZoom = 1,
  colorMode = "course",
  zoomControlsTop = 12,
  legible = false,
  focusCourseId = null,
  onHoverCourse,
  zoomRequest = null,
}: Props) {
  const mastery = colorMode === "mastery";
  const legibleRef = React.useRef(legible);
  // The current zoom, for the per-tick writer (legible nodes keep a minimum
  // on-screen size, so arrow insets depend on it).
  const viewScaleRef = React.useRef(initialZoom);
  React.useEffect(() => {
    legibleRef.current = legible;
  }, [legible]);
  const importance = React.useMemo(
    () => (legible ? importanceRadii(nodes, splitEdges(nodes, edges).concept) : null),
    [legible, nodes, edges],
  );
  const radiusMap = React.useMemo(
    () =>
      new Map(
        nodes.map((n) => [
          n.id,
          (!n.is_subject_root && importance?.get(n.id)) || radiusFor(n.mastery_score, n.is_subject_root),
        ]),
      ),
    [nodes, importance],
  );
  // Read by the per-tick writer and the collide force, outside React renders.
  const radiusRef = React.useRef(radiusMap);
  React.useEffect(() => {
    radiusRef.current = radiusMap;
  }, [radiusMap]);
  // Per-instance prefix for the edge-gradient ids: several graphs can share
  // a page, and SVG `url(#…)` references resolve document-wide.
  const gradPrefix = `kg${React.useId().replace(/[^a-zA-Z0-9_-]/g, "")}`;
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
  const initialView = React.useCallback(
    () => ({
      tx: (width / 2) * (1 - initialZoom),
      ty: (height / 2) * (1 - initialZoom),
      scale: initialZoom,
    }),
    [width, height, initialZoom],
  );
  const [view, setView] = React.useState(initialView);
  React.useEffect(() => {
    viewScaleRef.current = view.scale;
  }, [view.scale]);
  // The committed view, for handlers that ease from it; the eased target and
  // its animation frame.
  const viewNowRef = React.useRef(view);
  React.useEffect(() => {
    viewNowRef.current = view;
  }, [view]);
  const viewTargetRef = React.useRef<{ tx: number; ty: number; scale: number } | null>(null);
  const viewAnimRef = React.useRef<number | null>(null);
  React.useEffect(
    () => () => {
      if (viewAnimRef.current != null) cancelAnimationFrame(viewAnimRef.current);
    },
    [],
  );
  // A zoomed opening view is centred on the window, so a new window size
  // re-centres it — but only while the student hasn't moved it: once they
  // have panned or zoomed, a resize keeps their view. At the default zoom the
  // view is the identity at any size, so there is nothing to re-centre.
  const openedAt = React.useRef(view);
  React.useEffect(() => {
    if (initialZoom === 1) return;
    const next = initialView();
    const previous = openedAt.current;
    openedAt.current = next;
    setView(v =>
      v.tx === previous.tx && v.ty === previous.ty && v.scale === previous.scale ? next : v,
    );
  }, [initialZoom, initialView]);
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
  // `mastery` mode's per-edge gradients are in user space, so their endpoints
  // ride the same per-tick writes as the lines they paint.
  const gradElsRef = React.useRef(new Map<number, SVGLinearGradientElement>());
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
      // Legible mode ends each line at the target's rim so its arrow shows.
      const [ex, ey] = legibleRef.current
        ? lineEnd(s.x, s.y, t.x, t.y,
            Math.max(radiusRef.current.get(t.id) ?? 0, MIN_SCREEN_R / viewScaleRef.current) + 2)
        : [t.x, t.y];
      for (const target of [el, gradElsRef.current.get(i)]) {
        if (!target) continue;
        target.setAttribute("x1", String(s.x));
        target.setAttribute("y1", String(s.y));
        target.setAttribute("x2", String(target === el ? ex : t.x));
        target.setAttribute("y2", String(target === el ? ey : t.y));
      }
    });
  }, []);

  // Rebuild the simulation whenever the node/edge set fundamentally changes.
  // We diff by id so stable nodes keep their current x/y/vx/vy.
  const dataKey = React.useMemo(
    () => nodes.map((n) => n.id).join("|") + "::" + edges.map((e) => `${e.source}-${e.target}`).join("|"),
    [nodes, edges],
  );

  // Radial plan (rings per course) — read by the orbit force every tick.
  const planRef = React.useRef<RadialPlan>({ centers: new Map(), orbit: new Map() });
  // Course roots the student dragged keep their spot across re-plans.
  const movedRootsRef = React.useRef(new Set<string>());
  // Legible: where each free course root settles back to.
  const rootHomeRef = React.useRef(new Map<string, { x: number; y: number }>());
  // Set once the student pans or zooms; auto-fit never overrides them.
  const viewTouchedRef = React.useRef(false);
  const fittedViewRef = React.useRef<{ tx: number; ty: number; scale: number } | null>(null);

  React.useEffect(() => {
    // Course spokes are layout-only: the root is a position, never a hub, so
    // only real concept-to-concept edges join the simulation and the render.
    const { concept: conceptEdges } = splitEdges(nodes, edges);
    const plan = planRadial(nodes, conceptEdges, width, height);
    planRef.current = plan;

    // Open on the whole graph: when the planned rings overflow the window,
    // zoom out to fit — until the student pans or zooms themselves.
    const b = planBounds(plan, width, height);
    fittedViewRef.current = null;
    // Only at the default zoom: a caller that asks for its own opening zoom
    // (quiz home's neighbourhood fragment) has already chosen its framing.
    if (b && initialZoom === 1) {
      const bw = b.maxX - b.minX;
      const bh = b.maxY - b.minY;
      const scale = Math.max(MIN_ZOOM, Math.min(initialZoom, width / bw, height / bh));
      if (scale < initialZoom || bw > width || bh > height) {
        const mx = (b.minX + b.maxX) / 2;
        const my = (b.minY + b.maxY) / 2;
        fittedViewRef.current = { tx: width / 2 - mx * scale, ty: height / 2 - my * scale, scale };
        if (!viewTouchedRef.current) setView(fittedViewRef.current);
      }
    }

    // Merge new node data into existing sim nodes to preserve motion state.
    const byId = new Map(simNodesRef.current.map((n) => [n.id, n]));
    const nextNodes: SimNode[] = nodes.map((n) => {
      const prev = byId.get(n.id);
      const center = plan.centers.get(n.id);
      if (center && !movedRootsRef.current.has(n.id)) rootHomeRef.current.set(n.id, center);
      if (prev) {
        // Keep position + velocity; refresh mutable data fields (mastery, color).
        Object.assign(prev, n);
        if (center && legibleRef.current) {
          // Legible: a course root is free, held near its home by a spring,
          // so dragging its concepts can pull it along.
          prev.fx = null;
          prev.fy = null;
        } else if (center && !movedRootsRef.current.has(n.id)) {
          prev.fx = center.x;
          prev.fy = center.y;
        }
        return prev;
      }
      if (center) {
        const pin = legibleRef.current ? {} : { fx: center.x, fy: center.y };
        return { ...n, x: center.x, y: center.y, ...pin, vx: 0, vy: 0, index: undefined } as SimNode;
      }
      const o = plan.orbit.get(n.id);
      const c = (o?.rootId && plan.centers.get(o.rootId)) || { x: width / 2, y: height / 2 };
      const a = o?.angle ?? 0;
      const r = o?.radius ?? 80;
      return {
        ...n,
        x: c.x + Math.cos(a) * r,
        y: c.y + Math.sin(a) * r,
        vx: 0,
        vy: 0,
        index: undefined,
      } as SimNode;
    });

    const nextIds = new Set(nextNodes.map((n) => n.id));
    const nextLinks: SimLink[] = [
      ...courseLinks(plan).map((e) => ({ ...e, anchor: true })),
      ...conceptEdges.map((e) => ({ ...e, anchor: false })),
    ]
      .filter((e) => nextIds.has(e.source) && nextIds.has(e.target))
      .map((e) => ({
        source: e.source,
        target: e.target,
        strength: e.strength,
        relationship_type: e.relationship_type,
        anchor: e.anchor,
      }));

    simNodesRef.current = nextNodes;
    simLinksRef.current = nextLinks;

    if (!simRef.current) {
      simRef.current = forceSimulation<SimNode>(nextNodes).on("tick", applyPositions);
    } else {
      simRef.current.nodes(nextNodes);
    }

    const nodeById = new Map(nextNodes.map((n) => [n.id, n]));
    const centerOf = (rootId: string | null) => {
      const root = rootId ? nodeById.get(rootId) : undefined;
      if (root && root.x != null && root.y != null) return { x: root.x, y: root.y };
      return { x: width / 2, y: height / 2 };
    };

    const sim = simRef.current;
    sim
      .force(
        "link",
        forceLink<SimNode, SimLink>(nextLinks)
          .id((d) => d.id)
          .distance(56)
          .strength((l) => (l.anchor ? 0 : 0.06 + (l.strength || 0.5) * 0.12)),
      )
      .force("charge", forceManyBody<SimNode>().strength(-70).distanceMax(220))
      .force(
        "collide",
        forceCollide<SimNode>().radius((d) =>
          d.is_subject_root
            ? 40
            : legibleRef.current
              ? (radiusRef.current.get(d.id) ?? 8) + 13
              : 20 + (d.mastery_score || 0) * 6,
        ),
      )
      .force(
        "orbit",
        forceOrbit<SimNode>(() => planRef.current, centerOf, 0.55, 0.12, {
          // Legible: concepts tug their course root (elastic dragging).
          reaction: legibleRef.current ? 0.35 : 0,
          pushRoot: (rootId, dvx, dvy) => {
            const root = nodeById.get(rootId);
            if (!root || root.fx != null) return;
            root.vx = (root.vx ?? 0) + dvx;
            root.vy = (root.vy ?? 0) + dvy;
          },
        }),
      )
      .force("home", (alpha: number) => {
        // Legible: each free course root drifts back toward its home (where
        // it was planned, or where the student last left it).
        if (!legibleRef.current) return;
        for (const [id, home] of rootHomeRef.current) {
          const root = nodeById.get(id);
          if (!root || root.fx != null || root.x == null || root.y == null) continue;
          root.vx = (root.vx ?? 0) + (home.x - root.x) * 0.1 * alpha;
          root.vy = (root.vy ?? 0) + (home.y - root.y) * 0.1 * alpha;
        }
      });

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
  const nodeRadius = (n: GraphNode) => radiusMap.get(n.id) ?? radiusFor(n.mastery_score, n.is_subject_root);

  // Legible focus: the hovered concept and its direct neighbours — from the
  // props (concept edges + the course's inner-circle links), never the sim.
  const focusId = legible ? hovered?.id ?? null : null;
  // The same radial plan the simulation uses, recomputed from props for render.
  const planned = React.useMemo(() => {
    const { concept } = splitEdges(nodes, edges);
    const plan = planRadial(nodes, concept, width, height);
    // Each course's outermost ring, for its region label.
    const outer = new Map<string, number>();
    for (const o of plan.orbit.values()) {
      if (o.rootId) outer.set(o.rootId, Math.max(outer.get(o.rootId) ?? 0, o.radius));
    }
    const roots = nodes.filter((n) => n.is_subject_root);
    const rootOfCourse = new Map(roots.map((r) => [r.course_id, r.id]));
    return { concept, plan, outer, roots, rootOfCourse };
  }, [nodes, edges, width, height]);
  // A hovered "My courses" row (the host's key): that course stays bright.
  const inLegendFocus = (n: GraphNode) => !focusCourseId || n.course_id === focusCourseId;
  // The host's key asked to zoom to a course (Dashboard: click a row).
  const zoomSeq = zoomRequest?.seq;
  const zoomCourse = zoomRequest?.courseId;
  React.useEffect(() => {
    if (zoomSeq == null || !zoomCourse) return;
    const rootId = planned.rootOfCourse.get(zoomCourse);
    // Where the course is now (it may have been dragged), else where planned.
    const live = rootId ? simNodesRef.current.find((n) => n.id === rootId) : undefined;
    const c =
      live && live.x != null && live.y != null
        ? { x: live.x, y: live.y }
        : rootId ? planned.plan.centers.get(rootId) : undefined;
    if (!rootId || !c) return;
    const reach = (planned.outer.get(rootId) ?? 60) + 50;
    // Fit the course, but never so far out that its labels are still faded.
    const fit = Math.min(width / (reach * 2), height / (reach * 2));
    const scale = Math.min(MAX_ZOOM, Math.max(1.05, fit));
    viewTouchedRef.current = true;
    easeView({ tx: width / 2 - c.x * scale, ty: height / 2 - c.y * scale, scale });
    // Only a new request zooms; layout changes alone don't re-zoom.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [zoomSeq, zoomCourse]);
  const focusSet = React.useMemo(() => {
    const set = new Set<string>();
    if (!focusId) return set;
    set.add(focusId);
    const inner = courseLinks(planned.plan);
    for (const e of [...planned.concept, ...inner]) {
      if (e.source === focusId) set.add(e.target);
      if (e.target === focusId) set.add(e.source);
    }
    return set;
  }, [focusId, planned]);
  const courseColor = (n?: GraphNode) => {
    if (!n) return "var(--c-sage)";
    const base = n.color || "var(--c-sage)";
    if (n.is_subject_root) return base;
    return shadeFor(base, n.id);
  };
  // In legible mastery mode the course dot keeps its course colour, so it
  // matches the disc behind it and the legend.
  const fillFor = (n: GraphNode) =>
    mastery && !(legible && n.is_subject_root) ? masteryFillFor(n) : courseColor(n);

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

  // ── Smooth view changes (legible) ───────────────────────────────────────
  // Wheel, zoom buttons, reset and course zooms ease toward a target view
  // over a few frames instead of jumping. Other graphs (and test mode /
  // reduced motion) still jump, so their behaviour is unchanged.
  const easeView = (target: { tx: number; ty: number; scale: number }) => {
    const instant =
      !legible ||
      IS_TEST_MODE ||
      typeof requestAnimationFrame === "undefined" ||
      (typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches);
    if (instant) {
      viewTargetRef.current = null;
      setView(target);
      return;
    }
    viewTargetRef.current = target;
    if (viewAnimRef.current != null) return;
    let cur = viewNowRef.current;
    const step = () => {
      const t = viewTargetRef.current;
      if (!t) {
        viewAnimRef.current = null;
        return;
      }
      const k = 0.22;
      cur = { tx: cur.tx + (t.tx - cur.tx) * k, ty: cur.ty + (t.ty - cur.ty) * k, scale: cur.scale + (t.scale - cur.scale) * k };
      const done =
        Math.abs(cur.scale - t.scale) < 0.001 && Math.abs(cur.tx - t.tx) < 0.3 && Math.abs(cur.ty - t.ty) < 0.3;
      if (done) {
        cur = t;
        viewTargetRef.current = null;
      }
      setView(cur);
      viewAnimRef.current = done ? null : requestAnimationFrame(step);
    };
    viewAnimRef.current = requestAnimationFrame(step);
  };
  const stopEasing = () => {
    viewTargetRef.current = null;
    if (viewAnimRef.current != null) cancelAnimationFrame(viewAnimRef.current);
    viewAnimRef.current = null;
  };
  /** Zoom by `factor` about a window point, from wherever the view is headed. */
  const zoomAbout = (factor: number, mx: number, my: number) => {
    const base = viewTargetRef.current ?? viewNowRef.current;
    const nextScale = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, base.scale * factor));
    const f = nextScale / base.scale;
    const c = clampView(mx - (mx - base.tx) * f, my - (my - base.ty) * f, nextScale);
    easeView({ tx: c.tx, ty: c.ty, scale: nextScale });
  };

  const onNodePointerDown = (e: React.PointerEvent, n: SimNode) => {
    e.stopPropagation();
    (e.currentTarget as Element).setPointerCapture(e.pointerId);
    movedRef.current = false;
    dragRef.current = { kind: "node", nodeId: n.id, pointerId: e.pointerId };
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
    stopEasing();
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
      viewTouchedRef.current = true;
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
    if (drag.kind === "node" && legible) {
      // Legible: nothing snaps back. The course's home becomes wherever its
      // root has been pulled to, and each of its concepts keeps the angle it
      // now sits at around the root.
      const n = simNodesRef.current.find((sn) => sn.id === drag.nodeId);
      if (n) {
        // Drop it exactly where the pointer let go, not where the last tick
        // had got to.
        if (n.fx != null && n.fy != null) {
          n.x = n.fx;
          n.y = n.fy;
        }
        n.fx = null;
        n.fy = null;
        if (movedRef.current) {
          const root = simNodesRef.current.find((sn) => sn.is_subject_root && sn.course_id === n.course_id);
          if (root && root.x != null && root.y != null) {
            rootHomeRef.current.set(root.id, { x: root.x, y: root.y });
            movedRootsRef.current.add(root.id);
            for (const m of simNodesRef.current) {
              const o = planRef.current.orbit.get(m.id);
              if (!o || o.rootId !== root.id || m.x == null || m.y == null) continue;
              o.angle = Math.atan2(m.y - root.y, m.x - root.x);
              // The dropped concept also keeps its new distance from the course.
              if (m.id === n.id) o.radius = Math.max(40, Math.hypot(m.x - root.x, m.y - root.y));
            }
          }
        }
      }
      simRef.current?.alphaTarget(0);
    } else if (drag.kind === "node") {
      const n = simNodesRef.current.find((sn) => sn.id === drag.nodeId);
      if (n?.is_subject_root) {
        // Course roots stay pinned where they were dropped; their rings follow.
        if (movedRef.current) movedRootsRef.current.add(n.id);
        n.fx = n.x;
        n.fy = n.y;
      } else if (n) {
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
    viewTouchedRef.current = true;
    if (legible) {
      // Exponential, capped per event: a mouse wheel notch (deltaY ~100) and
      // a trackpad's many small deltas both feel even, then ease in.
      const d = Math.max(-120, Math.min(120, e.deltaY));
      zoomAbout(Math.exp(-d * 0.0022), mx, my);
      return;
    }
    const delta = -e.deltaY * 0.0015;
    setView((v) => {
      const nextScale = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, v.scale * (1 + delta)));
      const factor = nextScale / v.scale;
      const c = clampView(mx - (mx - v.tx) * factor, my - (my - v.ty) * factor, nextScale);
      return { tx: c.tx, ty: c.ty, scale: nextScale };
    });
  };

  const resetView = () => {
    viewTouchedRef.current = false;
    easeView(fittedViewRef.current ?? initialView());
  };

  const hoveredMastery = hovered
    ? hovered.is_subject_root
      ? subjectAverage[hovered.subject] ?? 0
      : hovered.mastery_score || 0
    : 0;

  const simNodes = simNodesRef.current;
  const simLinks = simLinksRef.current;
  const zoomLabels = labelOpacityAt(view.scale);
  // Legible nodes never shrink below MIN_SCREEN_R on screen, however far out.
  const drawRadius = (n: GraphNode) =>
    legible ? Math.max(nodeRadius(n), MIN_SCREEN_R / view.scale) : nodeRadius(n);
  // Labels of focused concepts stay readable however far out the view is.
  const focusFont = (size: number) => size / Math.min(1, view.scale);
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
        data-color-mode={colorMode}
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
          {legible && (
            <>
              <marker id={`${gradPrefix}-arrow`} viewBox="0 0 10 10" refX={9} refY={5}
                markerWidth={5} markerHeight={5} orient="auto">
                <path d="M0,0 L10,5 L0,10 z" fill="var(--text-muted)" />
              </marker>
              <marker id={`${gradPrefix}-arrow-on`} viewBox="0 0 10 10" refX={9} refY={5}
                markerWidth={5} markerHeight={5} orient="auto">
                <path d="M0,0 L10,5 L0,10 z" fill="var(--text-dim)" />
              </marker>
            </>
          )}
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
              const baseOp = mastery ? 0.85 : variant === "constellation" ? 0.35 : 0.2;
              const incident = !!focusId && (s.id === focusId || t.id === focusId);
              const op = !legible
                ? baseOp
                : focusId
                  ? incident ? 0.9 : 0.04
                  : !inLegendFocus(s) || !inLegendFocus(t)
                    ? 0.03
                    : l.anchor ? 0.1 : mastery ? 0.45 : 0.16;
              const directed = legible && !l.anchor && isDirected(l);
              // Arrowheads don't fade with their line, so a dimmed link drops its arrow.
              const arrow = directed && (focusId ? incident : view.scale >= 0.9);
              const [ex, ey] = legible ? lineEnd(s.x!, s.y!, t.x!, t.y!, drawRadius(t) + 2) : [t.x, t.y];
              const gradId = `${gradPrefix}-e${i}`;
              return (
                <React.Fragment key={i}>
                  {mastery && (
                    <defs>
                      <linearGradient
                        id={gradId}
                        ref={(el) => {
                          if (el) gradElsRef.current.set(i, el);
                          else gradElsRef.current.delete(i);
                        }}
                        gradientUnits="userSpaceOnUse"
                        x1={s.x}
                        y1={s.y}
                        x2={t.x}
                        y2={t.y}
                      >
                        <stop offset="0%" stopColor={fillFor(s)} />
                        <stop offset="100%" stopColor={fillFor(t)} />
                      </linearGradient>
                    </defs>
                  )}
                  <line
                    ref={(el) => {
                      if (el) edgeElsRef.current.set(i, el);
                      else edgeElsRef.current.delete(i);
                    }}
                    data-testid="graph-edge"
                    x1={s.x}
                    y1={s.y}
                    x2={ex}
                    y2={ey}
                    stroke={mastery ? `url(#${gradId})` : incident ? "var(--text-dim)" : "var(--text-muted)"}
                    strokeOpacity={op}
                    markerEnd={arrow ? `url(#${gradPrefix}-arrow${incident ? "-on" : ""})` : undefined}
                    style={legible ? { transition: "stroke-opacity 150ms ease" } : undefined}
                    strokeWidth={mastery ? edgeWidthFor(l.strength) * 1.6 : edgeWidthFor(l.strength)}
                    strokeLinecap="round"
                    strokeDasharray={l.relationship_type === "related" ? "4 4" : undefined}
                  />
                </React.Fragment>
              );
            })}
          </g>

          {/* Nodes */}
          <g>
            {simNodes.map((n) => {
              if (n.x == null || n.y == null) return null;
              const r = drawRadius(n);
              const color = fillFor(n);
              // `mastery` mode carries the tier in the hue, so every mark is
              // fully opaque; `course` mode carries it in the opacity.
              const op = n.is_subject_root || mastery ? 1 : opacityFor(n.mastery_tier);
              const isHl = highlightId === n.id;
              const isHovered = hovered?.id === n.id;
              // Course roots are always pinned by the radial layout, so a pin
              // only means "being dragged" for concepts.
              const isPinned = !n.is_subject_root && n.fx != null && n.fy != null;
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
                  style={
                    legible
                      ? {
                          cursor: "grab",
                          opacity:
                            (focusId && !focusSet.has(n.id)) || (!focusId && !inLegendFocus(n)) ? 0.15 : 1,
                          transition: "opacity 150ms ease",
                        }
                      : { cursor: "grab" }
                  }
                  onPointerDown={(ev) => onNodePointerDown(ev, n)}
                  onPointerEnter={(ev) => {
                    // Seed the tooltip position as it mounts so it opens
                    // under the cursor, not at a stale spot.
                    setTooltipPos({ x: ev.clientX, y: ev.clientY });
                    setHovered(n);
                    if (legible) onHoverCourse?.(n.course_id);
                  }}
                  onPointerLeave={() => {
                    setHovered((h) => (h?.id === n.id ? null : h));
                    if (legible) onHoverCourse?.(null);
                  }}
                  onClick={(ev) => {
                    ev.stopPropagation();
                    if (movedRef.current) return;
                    onNodeClick?.(n);
                  }}
                >
                  {legible && (
                    // A bigger, invisible hover/click target than the dot itself.
                    <circle cx={0} cy={0} r={r + Math.max(4, 10 / view.scale)} fill="transparent" />
                  )}
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
                  {n.is_subject_root && !legible && (
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
                      fontSize={legible && focusSet.has(n.id) ? Math.min(24, focusFont(10.5)) : 10.5}
                      fontWeight={legible && focusId === n.id ? 600 : undefined}
                      fill="var(--text-dim)"
                      opacity={
                        legible
                          ? (focusId ? (focusSet.has(n.id) ? 1 : 0) : zoomLabels) * 0.85
                          : 0.85
                      }
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
        data-testid="graph-zoom-controls"
        style={{
          position: "absolute",
          top: zoomControlsTop,
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
          onClick={() => {
            if (legible) {
              viewTouchedRef.current = true;
              zoomAbout(1.25, width / 2, height / 2);
              return;
            }
            setView((v) => {
              const s = Math.min(MAX_ZOOM, v.scale * 1.2);
              const c = clampView(v.tx, v.ty, s);
              return { tx: c.tx, ty: c.ty, scale: s };
            });
          }}
          title="Zoom in"
        >
          +
        </button>
        <button
          data-testid="graph-zoom-out"
          className="btn btn--ghost btn--sm"
          style={{ padding: "2px 8px", fontFamily: "var(--font-mono)" }}
          onClick={() => {
            if (legible) {
              viewTouchedRef.current = true;
              zoomAbout(1 / 1.25, width / 2, height / 2);
              return;
            }
            setView((v) => {
              const s = Math.max(MIN_ZOOM, v.scale / 1.2);
              const c = clampView(v.tx, v.ty, s);
              return { tx: c.tx, ty: c.ty, scale: s };
            });
          }}
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
