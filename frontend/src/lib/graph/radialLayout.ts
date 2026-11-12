// Course-centred radial layout for the knowledge graph.
//
// Each course root sits at a fixed centre and its concepts settle on rings
// around it, filled from the centre out in dependency order: the concepts
// nothing leads into sit innermost, and whatever a prerequisite / builds_on /
// part_of edge leads to sits beside or outside its source, never inside it.
// The course root is a position, not a hub: the synthesized course→concept
// spokes from /api/graph are dropped from both the render and the
// simulation, so only real concept-to-concept edges are drawn.
//
// Spacing is planned, not left to the simulation. Every concept gets
// `ARC_PER_NODE` of ring to itself and rings sit `RING_STEP` apart, which is
// the room a mark and its caption need. A course takes as few rings as seat
// it (`ringsFor`), so it is a compact disc whatever the shape of its
// dependencies, not one ring per level; and several courses are arranged
// the way that shows them largest in the window (`packCourses`). The whole
// graph opens as large as the window allows.
//
// Pure functions + one custom d3 force; the component owns the simulation.

import type { GraphEdge, GraphNode } from "@/lib/data";

export type RelationshipType = NonNullable<GraphEdge["relationship_type"]>;

const DIRECTED: ReadonlySet<string> = new Set(["prerequisite", "builds_on", "part_of"]);

// Spacing. A concept is a mark up to 40 across with a caption under it up to
// about 100 wide, so these leave room for both: neighbours on a ring do not
// sit on each other's captions, and a ring clears the captions of the ring
// inside it.
/** The innermost ring's smallest radius around its course root. */
export const RING0 = 96;
/** Gap between consecutive rings. */
export const RING_STEP = 68;
/** Arc length each concept gets on its ring. */
export const ARC_PER_NODE = 92;
/** Space kept around a course's outer ring when several courses share the canvas. */
export const COURSE_MARGIN = 80;
/**
 * Room past a course's outer ring when measuring a layout: for the marks on
 * it, their captions (wider than they are tall) and the little the
 * simulation lets a concept settle off its ring.
 */
export const RING_REACH = { x: 72, y: 52 } as const;
/** Each further ring of one level is turned by the golden angle, so rings do not line up. */
const RING_TURN = Math.PI * (3 - Math.sqrt(5));
/**
 * How much wider a course may be drawn to start at its smallest radius. Rings
 * packed from the centre out read as one even cluster; the most compact
 * answer is often the same rings pushed outward around an empty middle, for
 * a few percent less width.
 */
const FILL_TOLERANCE = 1.06;

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

/**
 * The rings `count` concepts sit on, inner first: each ring's radius and how
 * many concepts it seats. No ring is smaller than `minRadius`.
 *
 * One ring holding every concept grows with their number, and past a dozen
 * or so it is a wide, hollow wheel. They are split over rings `RING_STEP`
 * apart instead, as many as make the outer radius smallest: each concept
 * still has `ARC_PER_NODE` of ring to itself, in a fraction of the width.
 * Seats are shared out by circumference, so every ring is equally full.
 */
export function ringsFor(count: number, minRadius: number): Array<{ radius: number; count: number }> {
  if (count <= 0) return [];
  // What the rings' radii must add up to for every concept to have its arc.
  const need = (count * ARC_PER_NODE) / (2 * Math.PI);
  let rings = 1;
  let inner = Math.max(minRadius, need);
  for (let k = 2; k <= count && inner > minRadius; k++) {
    const candidate = Math.max(minRadius, (need - (RING_STEP * k * (k - 1)) / 2) / k);
    // Another ring helps only while it pulls the outer one in.
    if (candidate + (k - 1) * RING_STEP >= inner + (rings - 1) * RING_STEP) break;
    rings = k;
    inner = candidate;
  }
  // One more ring, starting from the smallest radius, when it costs next to
  // nothing: the course fills in from the centre instead of leaving it empty.
  if (rings > 1 && inner > minRadius && minRadius + rings * RING_STEP <= (inner + (rings - 1) * RING_STEP) * FILL_TOLERANCE) {
    rings += 1;
    inner = minRadius;
  }
  const radii = Array.from({ length: rings }, (_, i) => inner + i * RING_STEP);
  const total = radii.reduce((sum, r) => sum + r, 0);
  const exact = radii.map((r) => (count * r) / total);
  const seats = exact.map(Math.floor);
  // Hand out what rounding left over, largest remainder first (outer ring on a tie).
  const byRemainder = exact
    .map((e, i) => ({ i, rest: e - Math.floor(e) }))
    .sort((p, q) => q.rest - p.rest || q.i - p.i);
  for (let left = count - seats.reduce((sum, n) => sum + n, 0), j = 0; left > 0; left--, j++) {
    seats[byRemainder[j % rings].i] += 1;
  }
  return radii.map((radius, i) => ({ radius, count: seats[i] })).filter((ring) => ring.count > 0);
}

/**
 * Which ring each of a level's concepts takes, given them in angular order
 * and how many seats the level has on each ring: the rings are dealt out in
 * proportion to their seats, so each ring's share of the level is spread
 * through the whole order rather than bunched in one arc.
 */
function dealRings(count: number, seats: number[]): number[] {
  const taken = seats.map(() => 0);
  const out: number[] = [];
  for (let j = 0; j < count; j++) {
    let pick = 0;
    let owed = -Infinity;
    for (let k = 0; k < seats.length; k++) {
      if (taken[k] >= seats[k]) continue;
      // How far behind its share of the first j + 1 concepts this ring is.
      const due = (seats[k] * (j + 1)) / count - taken[k];
      if (due > owed + 1e-9) {
        owed = due;
        pick = k;
      }
    }
    taken[pick] += 1;
    out.push(pick);
  }
  return out;
}

/**
 * Where `count` courses sit, relative to the middle of the canvas: whichever
 * arrangement shows them largest in a `width` × `height` window. Each course
 * keeps a circle of radius `footprint` to itself; `reach` is how far its
 * marks and captions extend from its centre, across and down.
 *
 * The arrangements tried are rows (one row, two, … with rows of unequal
 * length centred, so they nest like a honeycomb and sit closer together) and
 * a ring of courses round the middle, point up or flat. Rows suit a wide
 * window and many courses; a ring suits a square one and a few. Courses fill
 * rows left to right, top to bottom, and a ring clockwise from the top.
 */
export function packCourses(
  count: number,
  footprint: number,
  reach: { x: number; y: number },
  width: number,
  height: number,
): Array<{ x: number; y: number }> {
  if (count <= 0) return [];
  if (count === 1) return [{ x: 0, y: 0 }];
  const w = Math.max(width, 1);
  const h = Math.max(height, 1);
  const candidates: Array<Array<{ x: number; y: number }>> = [];
  for (let r = 1; r <= count; r++) candidates.push(courseRows(rowLengths(count, r), footprint));
  if (count >= 3) {
    candidates.push(courseRing(count, footprint, -Math.PI / 2));
    candidates.push(courseRing(count, footprint, -Math.PI / 2 + Math.PI / count));
  }
  let best: { spots: Array<{ x: number; y: number }>; scale: number; fill: number } | null = null;
  for (const spots of candidates) {
    const xs = spots.map((p) => p.x);
    const ys = spots.map((p) => p.y);
    const midX = (Math.min(...xs) + Math.max(...xs)) / 2;
    const midY = (Math.min(...ys) + Math.max(...ys)) / 2;
    const spanX = Math.max(...xs) - Math.min(...xs) + 2 * reach.x;
    const spanY = Math.max(...ys) - Math.min(...ys) + 2 * reach.y;
    const scale = Math.min(w / spanX, h / spanY, 1);
    // When several arrangements fit at full size, take the one shaped like the window.
    const fill = Math.min((spanX * scale) / w, (spanY * scale) / h);
    if (!best || scale > best.scale + 1e-9 || (scale > best.scale - 1e-9 && fill > best.fill + 1e-9)) {
      // Centred on the middle of the canvas, whatever its own shape.
      best = { spots: spots.map((p) => ({ x: p.x - midX || 0, y: p.y - midY || 0 })), scale, fill };
    }
  }
  return best!.spots;
}

/** Courses in rows of the given lengths, each row centred; rows of unequal length nest. */
function courseRows(rows: number[], footprint: number): Array<{ x: number; y: number }> {
  const out: Array<{ x: number; y: number }> = [];
  let y = 0;
  rows.forEach((n, i) => {
    // Rows that differ in length are offset by half a cell: a honeycomb.
    if (i > 0) y += (n === rows[i - 1] ? 2 : Math.sqrt(3)) * footprint;
    for (let j = 0; j < n; j++) out.push({ x: (j - (n - 1) / 2) * 2 * footprint, y });
  });
  return out;
}

/** Courses on a circle wide enough to keep neighbours apart, clockwise from `start`. */
function courseRing(count: number, footprint: number, start: number): Array<{ x: number; y: number }> {
  const spread = footprint / Math.sin(Math.PI / count);
  return Array.from({ length: count }, (_, i) => {
    const a = start + (i / count) * Math.PI * 2;
    return { x: Math.cos(a) * spread, y: Math.sin(a) * spread };
  });
}

/**
 * `count` courses over `rows` rows, as evenly as they divide, longer and
 * shorter rows alternating so neighbouring rows can nest. A shorter row goes
 * on top when it can: it is centred, which leaves the window's top corners
 * (where a host puts its course key and zoom buttons) clear.
 */
function rowLengths(count: number, rows: number): number[] {
  const short = Math.floor(count / rows);
  let longLeft = count % rows;
  let shortLeft = rows - longLeft;
  const out: number[] = [];
  // Start with whichever there is more of (a short row on a tie), then
  // alternate while both remain.
  let long = longLeft > shortLeft;
  for (let i = 0; i < rows; i++) {
    if (long ? longLeft === 0 : shortLeft === 0) long = !long;
    out.push(long ? short + 1 : short);
    if (long) longLeft -= 1;
    else shortLeft -= 1;
    long = !long;
  }
  return out;
}

/** How many spots round each course a dropped course is tried at (`clearOfCourses`). */
const SPOTS_ROUND = 72;
/** Rounds of seat trading; a large course gets fewer, to bound the work. */
const UNTANGLE_ROUNDS = 16;
const UNTANGLE_LARGE = 400;

/**
 * Trade seats, two concepts at a time, while that shortens the course's
 * links. Seating each concept out from what leads into it leaves many links
 * running clear across the course, over other concepts and through each
 * other; shorter links cross less, so the course reads as a few strands
 * instead of a knot.
 *
 * A trade is only made between two starting concepts (`starts`, the ones
 * the course itself links to) or two that are not, and only when both still
 * sit level with or outside everything that leads into them: the course
 * still grows outward from its starting concepts. A course with no links
 * between its concepts is left exactly as seated. The order tried is by id,
 * so the same graph always ends up arranged the same way.
 */
function untangle(
  ids: string[],
  radius: Map<string, number>,
  angle: Map<string, number>,
  edges: GraphEdge[],
  starts: ReadonlySet<string>,
): void {
  const here = new Set(ids);
  const linked = new Map<string, string[]>();
  const into = new Map<string, string[]>();
  const outOf = new Map<string, string[]>();
  const push = (map: Map<string, string[]>, key: string, value: string) => {
    if (!map.has(key)) map.set(key, []);
    map.get(key)!.push(value);
  };
  for (const e of edges) {
    if (e.source === e.target || !here.has(e.source) || !here.has(e.target)) continue;
    push(linked, e.source, e.target);
    push(linked, e.target, e.source);
    if (isDirected(e)) {
      push(into, e.target, e.source);
      push(outOf, e.source, e.target);
    }
  }
  if (!linked.size) return;

  const x = new Map(ids.map((id) => [id, Math.cos(angle.get(id)!) * radius.get(id)!]));
  const y = new Map(ids.map((id) => [id, Math.sin(angle.get(id)!) * radius.get(id)!]));
  /** What `id`'s links would measure (squared) with it at (px, py) and `other` at (ox, oy). */
  const strain = (id: string, px: number, py: number, other: string, ox: number, oy: number) => {
    let sum = 0;
    for (const m of linked.get(id) ?? []) {
      const mx = m === other ? ox : x.get(m)!;
      const my = m === other ? oy : y.get(m)!;
      sum += (px - mx) * (px - mx) + (py - my) * (py - my);
    }
    return sum;
  };
  /** Whether `id` on a ring of radius `r`, with `other` on `otherR`, is still outside what leads into it. */
  const inOrder = (id: string, r: number, other: string, otherR: number) => {
    for (const p of into.get(id) ?? []) if ((p === other ? otherR : radius.get(p)!) > r + 1e-6) return false;
    for (const q of outOf.get(id) ?? []) if ((q === other ? otherR : radius.get(q)!) < r - 1e-6) return false;
    return true;
  };

  const order = [...ids].sort((a, b) => a.localeCompare(b));
  const rounds = ids.length > UNTANGLE_LARGE ? 3 : UNTANGLE_ROUNDS;
  for (let round = 0; round < rounds; round++) {
    let traded = false;
    for (let i = 0; i < order.length; i++) {
      const a = order[i];
      for (let j = i + 1; j < order.length; j++) {
        const b = order[j];
        // Two concepts with no links have nothing to gain from each other.
        if (!linked.has(a) && !linked.has(b)) continue;
        if (starts.has(a) !== starts.has(b)) continue;
        const ax = x.get(a)!, ay = y.get(a)!, bx = x.get(b)!, by = y.get(b)!;
        const ra = radius.get(a)!, rb = radius.get(b)!;
        const now = strain(a, ax, ay, b, bx, by) + strain(b, bx, by, a, ax, ay);
        const then = strain(a, bx, by, b, ax, ay) + strain(b, ax, ay, a, bx, by);
        if (then >= now - 1) continue;
        if (!inOrder(a, rb, b, ra) || !inOrder(b, ra, a, rb)) continue;
        const aa = angle.get(a)!;
        radius.set(a, rb); angle.set(a, angle.get(b)!); x.set(a, bx); y.set(a, by);
        radius.set(b, ra); angle.set(b, aa); x.set(b, ax); y.set(b, ay);
        traded = true;
      }
    }
    if (!traded) break;
  }
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

const TAU = Math.PI * 2;
/** An angle in [0, 2π). */
const norm = (a: number) => ((a % TAU) + TAU) % TAU;
/** The mean direction of some angles. */
function meanAngle(angles: number[]): number {
  return Math.atan2(
    angles.reduce((sum, a) => sum + Math.sin(a), 0),
    angles.reduce((sum, a) => sum + Math.cos(a), 0),
  );
}

/** What leads into each of a course's concepts (directed edges within the course). */
function predecessorsOf(depth: ReadonlyMap<string, number>, edges: GraphEdge[]): Map<string, string[]> {
  const preds = new Map<string, string[]>();
  for (const e of edges) {
    if (!isDirected(e) || !depth.has(e.source) || !depth.has(e.target)) continue;
    if (!preds.has(e.target)) preds.set(e.target, []);
    preds.get(e.target)!.push(e.source);
  }
  return preds;
}

/**
 * Which ring each of a course's concepts sits on. They fill the rings from
 * the centre out in dependency order, so a concept never sits inside
 * something that leads into it. A level that runs over the end of a ring is
 * dealt across the rings it touches, so its concepts are spread all the way
 * round each one. Also returns `rough`: where each concept would like to be
 * before the seats are known, by its id for a starting concept, else toward
 * what leads into it.
 */
function seatByDepth(
  rings: Array<{ radius: number; count: number }>,
  byDepth: ReadonlyMap<number, string[]>,
  preds: ReadonlyMap<string, string[]>,
): { seated: string[][]; rough: Map<string, number> } {
  const seated: string[][] = rings.map(() => []);
  const free = rings.map((ring) => ring.count);
  const rough = new Map<string, number>();
  let at = 0;
  for (const d of [...byDepth.keys()].sort((a, b) => a - b)) {
    const level = byDepth
      .get(d)!
      .map((id) => {
        const from = (preds.get(id) || []).filter((p) => rough.has(p)).map((p) => rough.get(p)!);
        return { id, a: from.length ? norm(meanAngle(from)) : stableAngle(id) };
      })
      .sort((p, q) => p.a - q.a || p.id.localeCompare(q.id));
    for (const { id, a } of level) rough.set(id, a);
    const first = at;
    const take: number[] = [];
    // There is a seat for every concept, so this always ends with none left.
    for (let left = level.length; left > 0 && free[at] > 0; ) {
      const n = Math.min(free[at], left);
      take.push(n);
      free[at] -= n;
      left -= n;
      if (free[at] === 0 && at < rings.length - 1) at += 1;
    }
    const ringOf = dealRings(level.length, take);
    level.forEach(({ id }, j) => seated[first + ringOf[j]].push(id));
  }
  return { seated, rough };
}

/**
 * Angles, ring by ring from the centre: each ring's concepts go all the way
 * round it (a course with one starting concept would otherwise grow off to
 * one side), in the order of where they want to be and turned to sit as
 * close to that as an even spacing allows. A concept wants to be out from
 * what leads into it, so links mostly point outward.
 */
function spreadRings(
  rings: Array<{ radius: number; count: number }>,
  seated: string[][],
  preds: ReadonlyMap<string, string[]>,
  rough: ReadonlyMap<string, number>,
  offset: number,
): { angle: Map<string, number>; radius: Map<string, number> } {
  const angle = new Map<string, number>();
  const radius = new Map<string, number>();
  const want = (id: string): number => {
    const from = (preds.get(id) || []).map((p) => angle.get(p) ?? rough.get(p)).filter((a) => a != null);
    return from.length ? norm(meanAngle(from as number[])) : stableAngle(id);
  };
  rings.forEach((ring, k) => {
    const members = seated[k]
      .map((id) => ({ id, a: want(id) }))
      .sort((p, q) => p.a - q.a || p.id.localeCompare(q.id));
    const step = TAU / members.length;
    let base: number;
    if (members.every(({ id }) => !(preds.get(id) || []).length)) {
      // Nothing leads into any of them: a stable order, each further ring
      // turned so the rings do not line up.
      base = offset + k * RING_TURN;
    } else if (members.length === 1) {
      base = members[0].a;
    } else {
      base = meanAngle(members.map(({ a }, i) => a - i * step));
    }
    members.forEach(({ id }, i) => {
      angle.set(id, base + i * step);
      radius.set(id, ring.radius);
    });
  });
  return { angle, radius };
}

/**
 * One course's seats. The course takes as few rings as seat it comfortably
 * (`ringsFor`), its concepts are seated by dependency (`seatByDepth`) and
 * spread round their rings (`spreadRings`), then trade seats while that
 * shortens their links (`untangle`). `reach` is its outer ring's radius.
 */
function planCourse(
  ids: string[],
  conceptEdges: GraphEdge[],
  rootId: string | null,
): { seats: Map<string, { radius: number; angle: number; depth: number }>; reach: number } {
  const depth = computeDepths(ids, conceptEdges);
  const byDepth = new Map<number, string[]>();
  for (const id of ids) {
    const d = depth.get(id) ?? 0;
    if (!byDepth.has(d)) byDepth.set(d, []);
    byDepth.get(d)!.push(id);
  }
  const preds = predecessorsOf(depth, conceptEdges);
  const rings = ringsFor(ids.length, RING0);
  const { seated, rough } = seatByDepth(rings, byDepth, preds);
  const { angle, radius } = spreadRings(rings, seated, preds, rough, rootId ? stableAngle(rootId) : 0);
  untangle(ids, radius, angle, conceptEdges, rootId ? new Set(byDepth.get(0) ?? []) : new Set());
  const seats = new Map(
    ids.map((id) => [id, { radius: radius.get(id)!, angle: angle.get(id)!, depth: depth.get(id) ?? 0 }] as const),
  );
  return { seats, reach: rings.length ? rings[rings.length - 1].radius : 0 };
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
    const { seats, reach } = planCourse(members.map((m) => m.id), conceptEdges, rootId);
    for (const [id, seat] of seats) orbit.set(id, { rootId, ...seat });
    outer.set(rootId, reach);
  }

  // Course centres: one course sits in the middle; several are arranged the
  // way that shows them largest in the window, each with room around its
  // outer ring.
  const centers: RadialPlan["centers"] = new Map();
  const cx = width / 2;
  const cy = height / 2;
  const rootIds = roots.map((r) => r.id);
  const widest = Math.max(RING0, ...rootIds.map((id) => outer.get(id) ?? 0));
  const spots = packCourses(
    rootIds.length,
    widest + COURSE_MARGIN,
    { x: widest + RING_REACH.x, y: widest + RING_REACH.y },
    width,
    height,
  );
  rootIds.forEach((id, i) => centers.set(id, { x: cx + spots[i].x, y: cy + spots[i].y }));
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
  const grow = (x: number, y: number, rx: number, ry: number) => {
    minX = Math.min(minX, x - rx); maxX = Math.max(maxX, x + rx);
    minY = Math.min(minY, y - ry); maxY = Math.max(maxY, y + ry);
  };
  for (const c of plan.centers.values()) grow(c.x, c.y, 40, 40);
  for (const o of plan.orbit.values()) {
    const c = (o.rootId && plan.centers.get(o.rootId)) || { x: width / 2, y: height / 2 };
    grow(c.x, c.y, o.radius + RING_REACH.x, o.radius + RING_REACH.y);
  }
  return Number.isFinite(minX) ? { minX, minY, maxX, maxY } : null;
}

/**
 * The seat a dropped concept takes: of all the seats in its own course, the
 * one nearest to where it was let go (`dx`, `dy` from the course's centre).
 * Returns the concept sitting there now, which is the dropped concept itself
 * while its own seat is still the nearest.
 *
 * A seat is a place (a ring and an angle on it), and a course's seats are
 * what the plan spaced out. Concepts only ever trade them (`swapSeats`), so
 * however a student moves concepts about, they stay as far apart as planned.
 */
export function nearestSeat(orbit: RadialPlan["orbit"], id: string, dx: number, dy: number): string {
  const own = orbit.get(id);
  if (!own) return id;
  const reach = (o: { radius: number; angle: number }) =>
    Math.hypot(Math.cos(o.angle) * o.radius - dx, Math.sin(o.angle) * o.radius - dy);
  let best = id;
  // Its own seat wins a tie: a concept let go where it sat stays put.
  let nearest = reach(own);
  for (const [other, o] of orbit) {
    if (other === id || o.rootId !== own.rootId) continue;
    const d = reach(o);
    if (d < nearest - 1e-9) {
      nearest = d;
      best = other;
    }
  }
  return best;
}

/**
 * Two concepts of one course trade seats. Each keeps its own depth, which
 * says what leads into the concept, not where it sits.
 */
export function swapSeats(orbit: RadialPlan["orbit"], a: string, b: string): void {
  const first = orbit.get(a);
  const second = orbit.get(b);
  if (!first || !second || a === b || first.rootId !== second.rootId) return;
  [first.radius, second.radius] = [second.radius, first.radius];
  [first.angle, second.angle] = [second.angle, first.angle];
}

/**
 * Where a dropped course comes to rest: where it was let go when that is
 * clear of every other course, else the nearest spot that is. `keep` is the
 * least distance allowed between its centre and that course's. A course
 * dropped onto another is set down beside it rather than left tangled in it.
 *
 * The spots tried are those right at the allowed distance from some course,
 * all the way round it. `within` lists areas to keep to, most wanted first
 * (the part of the window the whole course fits in, then the part its centre
 * is visible in): a spot inside one is preferred to a nearer spot outside,
 * so a course is not set down off the edge of the window while there is
 * room in it. Courses take up a bounded space, so there is always a clear
 * spot on its edge.
 */
export function clearOfCourses(
  at: { x: number; y: number },
  others: ReadonlyArray<{ x: number; y: number; keep: number }>,
  within: ReadonlyArray<{ minX: number; minY: number; maxX: number; maxY: number }> = [],
): { x: number; y: number } {
  const clear = (p: { x: number; y: number }) =>
    others.every((o) => Math.hypot(p.x - o.x, p.y - o.y) >= o.keep - 1e-6);
  if (clear(at)) return at;
  const spots: Array<{ x: number; y: number }> = [];
  for (const o of others) {
    // Starting straight out from that course through the drop point: with
    // nothing else in the way, that is the least the course can be moved.
    const out = Math.atan2(at.y - o.y, at.x - o.x);
    for (let i = 0; i < SPOTS_ROUND; i++) {
      const a = out + (i / SPOTS_ROUND) * Math.PI * 2;
      const spot = { x: o.x + Math.cos(a) * o.keep, y: o.y + Math.sin(a) * o.keep };
      if (clear(spot)) spots.push(spot);
    }
  }
  // Only if every sampled spot were covered; kept so the answer is always a point.
  if (!spots.length) return at;
  let pool = spots;
  for (const area of within) {
    const inside = spots.filter((p) => p.x >= area.minX && p.x <= area.maxX && p.y >= area.minY && p.y <= area.maxY);
    if (inside.length) {
      pool = inside;
      break;
    }
  }
  let best = at;
  let nearest = Infinity;
  for (const spot of pool) {
    const d = Math.hypot(spot.x - at.x, spot.y - at.y);
    if (d < nearest - 1e-9) {
      nearest = d;
      best = spot;
    }
  }
  return best;
}

type Positioned = { id: string; x?: number; y?: number; vx?: number; vy?: number };

/** The furthest round its course a concept heads in one go when walking to its seat. */
const WALK_STEP = Math.PI / 4;

/**
 * A custom d3 force drawing each concept toward its seat: the point on its
 * ring, at its angle, around its course root's CURRENT position (so moving a
 * course moves its rings along).
 *
 * A concept whose seat is far round the course (a swap sent it to the other
 * side) walks there: it heads for a point at most `WALK_STEP` further round,
 * half a ring outside the larger of its distance and its seat's, so it goes
 * round the course between the rings instead of through the middle, where
 * the course root would stop it dead.
 */
export function forceOrbit<N extends Positioned>(
  plan: () => RadialPlan,
  centerOf: (rootId: string | null) => { x: number; y: number },
  strength = 0.3,
) {
  let nodes: N[] = [];
  const force = (alpha: number) => {
    const { orbit } = plan();
    for (const n of nodes) {
      const o = orbit.get(n.id);
      if (!o || n.x == null || n.y == null) continue;
      const c = centerOf(o.rootId);
      let tx = c.x + Math.cos(o.angle) * o.radius;
      let ty = c.y + Math.sin(o.angle) * o.radius;
      const dx = n.x - c.x;
      const dy = n.y - c.y;
      const r = Math.hypot(dx, dy);
      if (r > 1) {
        const here = Math.atan2(dy, dx);
        // The shorter way round, in (-π, π]; from exactly opposite, either way.
        const turn = Math.atan2(Math.sin(o.angle - here), Math.cos(o.angle - here));
        if (Math.abs(turn) > WALK_STEP) {
          const a = here + Math.sign(turn) * WALK_STEP;
          const walk = Math.max(r, o.radius) + RING_STEP / 2;
          tx = c.x + Math.cos(a) * walk;
          ty = c.y + Math.sin(a) * walk;
        }
      }
      n.vx = (n.vx ?? 0) + (tx - n.x) * strength * alpha;
      n.vy = (n.vy ?? 0) + (ty - n.y) * strength * alpha;
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

/** The zoom at which concept labels start to show, and the zoom they are full by. */
export const LABEL_ZOOM = { hidden: 0.55, full: 0.9 } as const;

/**
 * Concept-label opacity at a zoom level: hidden zoomed out (the text is too
 * small to read and only adds noise), full by 0.9×, so a graph that opens a
 * little under full size still opens with its labels.
 */
export function labelOpacityAt(scale: number): number {
  return Math.max(0, Math.min(1, (scale - LABEL_ZOOM.hidden) / (LABEL_ZOOM.full - LABEL_ZOOM.hidden)));
}
