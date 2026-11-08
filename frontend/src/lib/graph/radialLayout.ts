// Course-centred radial layout for the knowledge graph.
//
// Each course root sits at a fixed centre and its concepts settle on rings
// around it: ring 0 holds the concepts nothing leads into, and each
// prerequisite / builds_on / part_of edge pushes its target one ring further
// out. The course root is a position, not a hub: the synthesized
// course→concept spokes from /api/graph are dropped from both the render and
// the simulation, so only real concept-to-concept edges are drawn.
//
// Pure functions + one custom d3 force; the component owns the simulation.

import type { GraphEdge, GraphNode } from "@/lib/data";

export type RelationshipType = NonNullable<GraphEdge["relationship_type"]>;

const DIRECTED: ReadonlySet<string> = new Set(["prerequisite", "builds_on", "part_of"]);

/** Ring 0's radius around its course root. */
const RING0 = 62;
/** Minimum gap between consecutive rings. */
const RING_STEP = 48;
/** Arc length each concept wants on its ring before the ring grows. */
const ARC_PER_NODE = 52;
/** Space kept around a course's outer ring when several courses share the canvas. */
const COURSE_MARGIN = 70;

export function isDirected(e: Pick<GraphEdge, "relationship_type">): boolean {
  return DIRECTED.has(e.relationship_type ?? "");
}

/** The synthesized course spokes: any edge touching a course root. */
export function splitEdges(nodes: GraphNode[], edges: GraphEdge[]) {
  const roots = new Set(nodes.filter((n) => n.is_subject_root).map((n) => n.id));
  const concept: GraphEdge[] = [];
  const anchors: GraphEdge[] = [];
  for (const e of edges) {
    (roots.has(e.source) || roots.has(e.target) ? anchors : concept).push(e);
  }
  return { concept, anchors };
}

/**
 * Longest-path depth over directed concept edges. Cycles (which the backend
 * should never write, but the data is student-shaped) are cut by bounding the
 * relaxation passes at the node count.
 */
export function computeDepths(ids: string[], edges: GraphEdge[]): Map<string, number> {
  const depth = new Map(ids.map((id) => [id, 0]));
  const directed = edges.filter((e) => isDirected(e) && depth.has(e.source) && depth.has(e.target));
  for (let pass = 0; pass < ids.length; pass++) {
    let changed = false;
    for (const e of directed) {
      const next = (depth.get(e.source) ?? 0) + 1;
      if (next > (depth.get(e.target) ?? 0) && next < ids.length) {
        depth.set(e.target, next);
        changed = true;
      }
    }
    if (!changed) break;
  }
  return depth;
}

export type RadialPlan = {
  /** Course root id → fixed centre. */
  centers: Map<string, { x: number; y: number }>;
  /** Concept id → the root it orbits and its ring radius. */
  orbit: Map<string, { rootId: string | null; radius: number; angle: number; depth: number }>;
};

function stableAngle(id: string): number {
  let h = 0;
  for (let i = 0; i < id.length; i++) h = ((h << 5) - h + id.charCodeAt(i)) | 0;
  return ((h >>> 0) % 3600) / 3600 * Math.PI * 2;
}

/**
 * Plan rings and centres. Concepts whose course root is not in the node set
 * (a quiz neighbourhood fragment) orbit the canvas centre instead.
 */
export function planRadial(
  nodes: GraphNode[],
  conceptEdges: GraphEdge[],
  width: number,
  height: number,
): RadialPlan {
  const roots = nodes.filter((n) => n.is_subject_root);
  const rootByCourse = new Map(roots.map((r) => [r.course_id, r.id]));
  const groups = new Map<string | null, GraphNode[]>();
  for (const n of nodes) {
    if (n.is_subject_root) continue;
    const key = rootByCourse.get(n.course_id) ?? null;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key)!.push(n);
  }

  const orbit: RadialPlan["orbit"] = new Map();
  const outer = new Map<string | null, number>();
  for (const [rootId, members] of groups) {
    const ids = members.map((m) => m.id);
    const depth = computeDepths(ids, conceptEdges);
    const byDepth = new Map<number, string[]>();
    for (const id of ids) {
      const d = depth.get(id) ?? 0;
      if (!byDepth.has(d)) byDepth.set(d, []);
      byDepth.get(d)!.push(id);
    }
    // Ring radius: at least RING0 + d·STEP, grown so the ring's concepts fit.
    const radiusAt = new Map<number, number>();
    let prev = 0;
    for (const d of [...byDepth.keys()].sort((a, b) => a - b)) {
      const count = byDepth.get(d)!.length;
      const r = Math.max(RING0 + d * RING_STEP, prev + RING_STEP * (prev ? 1 : 0), (count * ARC_PER_NODE) / (2 * Math.PI));
      radiusAt.set(d, r);
      prev = r;
    }
    // Seed angles ring by ring: ring 0 in a stable order, deeper rings near
    // the mean angle of what leads into them, so links mostly point outward.
    const angle = new Map<string, number>();
    const preds = new Map<string, string[]>();
    for (const e of conceptEdges) {
      if (!isDirected(e)) continue;
      if (!preds.has(e.target)) preds.set(e.target, []);
      preds.get(e.target)!.push(e.source);
    }
    const offset = rootId ? stableAngle(rootId) : 0;
    for (const d of [...byDepth.keys()].sort((a, b) => a - b)) {
      const ring = byDepth.get(d)!;
      const want = (id: string) => {
        const ps = (preds.get(id) || []).filter((p) => angle.has(p));
        if (!ps.length) return stableAngle(id);
        const sx = ps.reduce((s, p) => s + Math.cos(angle.get(p)!), 0);
        const sy = ps.reduce((s, p) => s + Math.sin(angle.get(p)!), 0);
        return Math.atan2(sy, sx);
      };
      const TAU = Math.PI * 2;
      const norm = (a: number) => ((a % TAU) + TAU) % TAU;
      if (d === 0) {
        // The inner circle spreads evenly all the way round the course.
        const sorted = ring.map((id) => ({ id, a: stableAngle(id) })).sort((p, q) => p.a - q.a || p.id.localeCompare(q.id));
        sorted.forEach(({ id }, i) => angle.set(id, offset + (i / sorted.length) * TAU));
        continue;
      }
      // Deeper circles also go all the way round (a course with one starting
      // concept would otherwise grow off to one side), ordered by the angle of
      // what leads into each concept and turned to sit as close to it as an
      // even spacing allows.
      const sorted = ring.map((id) => ({ id, a: norm(want(id)) })).sort((p, q) => p.a - q.a || p.id.localeCompare(q.id));
      const step = TAU / sorted.length;
      let sx = 0, sy = 0;
      sorted.forEach(({ a }, i) => { sx += Math.cos(a - i * step); sy += Math.sin(a - i * step); });
      const base = sorted.length === 1 ? sorted[0].a : Math.atan2(sy, sx);
      sorted.forEach(({ id }, i) => angle.set(id, base + i * step));
    }
    for (const id of ids) {
      const d = depth.get(id) ?? 0;
      orbit.set(id, { rootId, radius: radiusAt.get(d)!, angle: angle.get(id)!, depth: d });
    }
    outer.set(rootId, Math.max(0, ...radiusAt.values()));
  }

  // Course centres: one course sits in the middle; several sit on a circle
  // wide enough that neighbouring courses' outer rings don't overlap.
  const centers: RadialPlan["centers"] = new Map();
  const cx = width / 2;
  const cy = height / 2;
  const rootIds = roots.map((r) => r.id);
  if (rootIds.length === 1) {
    centers.set(rootIds[0], { x: cx, y: cy });
  } else if (rootIds.length > 1) {
    const k = rootIds.length;
    const footprint = Math.max(...rootIds.map((id) => outer.get(id) ?? RING0)) + COURSE_MARGIN;
    const spread = k === 2 ? footprint : footprint / Math.sin(Math.PI / k);
    // Two courses sit side by side; more go round a circle from the top.
    const start = k === 2 ? Math.PI : -Math.PI / 2;
    rootIds.forEach((id, i) => {
      const a = start + (i / k) * Math.PI * 2;
      centers.set(id, { x: cx + Math.cos(a) * spread, y: cy + Math.sin(a) * spread });
    });
  }
  return { centers, orbit };
}

/**
 * The course's own links: one to each inner-circle concept (nothing leads
 * into it). Outer concepts hang off inner ones, never off the course. Built
 * here rather than taken from /api/graph, whose spokes go to every concept.
 */
export function courseLinks(plan: RadialPlan): GraphEdge[] {
  const out: GraphEdge[] = [];
  for (const [id, o] of plan.orbit) {
    if (o.rootId && o.depth === 0) out.push({ source: o.rootId, target: id, strength: 0.5, relationship_type: "part_of" });
  }
  return out;
}

/** Where the planned layout reaches, with room for labels. */
export function planBounds(plan: RadialPlan, width: number, height: number) {
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  const grow = (x: number, y: number, r: number) => {
    minX = Math.min(minX, x - r); maxX = Math.max(maxX, x + r);
    minY = Math.min(minY, y - r); maxY = Math.max(maxY, y + r);
  };
  for (const c of plan.centers.values()) grow(c.x, c.y, 40);
  for (const o of plan.orbit.values()) {
    const c = (o.rootId && plan.centers.get(o.rootId)) || { x: width / 2, y: height / 2 };
    grow(c.x, c.y, o.radius + 36);
  }
  return Number.isFinite(minX) ? { minX, minY, maxX, maxY } : null;
}

type Positioned = { id: string; x?: number; y?: number; vx?: number; vy?: number };

/**
 * A custom d3 force pulling each concept toward its ring around its course
 * root's CURRENT position (so dragging a course drags its rings along).
 */
export function forceOrbit<N extends Positioned>(
  plan: () => RadialPlan,
  centerOf: (rootId: string | null) => { x: number; y: number },
  strength = 0.6,
  anglePull = 0.12,
  {
    pushRoot,
    reaction = 0,
  }: {
    /** Apply the opposite tug to the course root (velocity deltas). */
    pushRoot?: (rootId: string, dvx: number, dvy: number) => void;
    /** Share of each concept's pull handed back to its root (0 = root fixed). */
    reaction?: number;
  } = {},
) {
  let nodes: N[] = [];
  const force = (alpha: number) => {
    const { orbit } = plan();
    for (const n of nodes) {
      const o = orbit.get(n.id);
      if (!o || n.x == null || n.y == null) continue;
      const c = centerOf(o.rootId);
      const dx = n.x - c.x || 1e-6;
      const dy = n.y - c.y || 1e-6;
      const len = Math.hypot(dx, dy);
      const k = ((o.radius - len) * strength * alpha) / len;
      // A gentler pull toward the planned angle, so link forces can't drag a
      // whole course round to one side of its centre.
      const tx = c.x + Math.cos(o.angle) * o.radius;
      const ty = c.y + Math.sin(o.angle) * o.radius;
      const ax = dx * k + (tx - n.x) * anglePull * alpha;
      const ay = dy * k + (ty - n.y) * anglePull * alpha;
      n.vx = (n.vx ?? 0) + ax;
      n.vy = (n.vy ?? 0) + ay;
      // Equal and opposite, in part: a concept pulled far from its course
      // tugs the course after it, and the course carries its other concepts.
      if (reaction && pushRoot && o.rootId) pushRoot(o.rootId, -ax * reaction, -ay * reaction);
    }
  };
  force.initialize = (ns: N[]) => {
    nodes = ns;
  };
  return force;
}

/**
 * Node radius by importance (Obsidian sizes notes by their links): how many
 * concepts sit downstream of this one through prerequisite / builds_on /
 * part_of edges, so foundations read big. With no directed edges at all it
 * falls back to plain link count; with no edges every concept is the base size.
 */
export function importanceRadii(
  nodes: GraphNode[],
  conceptEdges: GraphEdge[],
  { base = 9, extra = 14 }: { base?: number; extra?: number } = {},
): Map<string, number> {
  const ids = nodes.filter((n) => !n.is_subject_root).map((n) => n.id);
  const known = new Set(ids);
  const edges = conceptEdges.filter((e) => known.has(e.source) && known.has(e.target));
  const directed = edges.filter(isDirected);
  const score = new Map(ids.map((id) => [id, 0]));
  if (directed.length) {
    const out = new Map<string, string[]>();
    for (const e of directed) {
      if (!out.has(e.source)) out.set(e.source, []);
      out.get(e.source)!.push(e.target);
    }
    for (const id of ids) {
      const seen = new Set<string>();
      const stack = [...(out.get(id) || [])];
      while (stack.length) {
        const next = stack.pop()!;
        if (seen.has(next) || next === id) continue;
        seen.add(next);
        stack.push(...(out.get(next) || []));
      }
      score.set(id, seen.size);
    }
  } else {
    for (const e of edges) {
      score.set(e.source, (score.get(e.source) ?? 0) + 1);
      score.set(e.target, (score.get(e.target) ?? 0) + 1);
    }
  }
  const max = Math.max(0, ...score.values());
  return new Map(ids.map((id) => [id, max ? base + extra * Math.sqrt((score.get(id) ?? 0) / max) : base + 2]));
}

/** Concept-label opacity at a zoom level: hidden zoomed out, full by 1.05×. */
export function labelOpacityAt(scale: number): number {
  return Math.max(0, Math.min(1, (scale - 0.62) / (1.05 - 0.62)));
}
