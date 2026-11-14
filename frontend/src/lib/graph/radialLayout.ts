// Course layout for the knowledge graph: each course is an organic group of
// concepts round its course root, shaped by the links between them.
//
// A course root links to a few of its starting concepts, the biggest strands
// first: a hub, never a wheel. Its concepts are then planned the way their
// links make them, not on rings:
//
// - Everything joined to the root through links is laid out by distance in
//   the graph (stress majorization): linked concepts sit a link apart,
//   chains run out as strands, close-knit concepts stay together. Distances
//   are capped at the course's own width, so a long prerequisite chain coils
//   up instead of running off the screen.
// - Every other group (two concepts linked only to each other, a concept
//   with no links yet) is set down in the nearest free room round them,
//   nearest by a lobed measure each course draws from its own id, so a
//   course grows into an irregular shape of its own rather than a disc.
// - Concepts then trade places while that shortens their links, the links
//   settle, the course is turned to a shape a little wider than tall (the
//   same for every window, so a resize never re-plans it), and a last pass
//   keeps every concept clear of the others' captions and of the course root.
// - Last, the course root moves into the middle of its concepts, to the
//   roomiest spot there (`centreRoot`); the few concepts right beside it make
//   room, and nothing else moves.
//
// The synthesized course→concept spokes from /api/graph are dropped: the
// root's own links are `courseLinks`, and only real concept-to-concept edges
// are drawn besides. The plan gives each concept its place; the component's
// simulation holds it near there with the orbit force (`forceOrbit`) while
// links pull, concepts push apart and drags play out. Several courses are
// packed side by side by their planned boxes, whichever way shows them
// largest (`packCourses`). The same graph always gets the same plan, whatever
// order its nodes and edges come in.
//
// Pure functions + one custom d3 force; the component owns the simulation.

import type { GraphEdge, GraphNode } from "@/lib/data";

export type RelationshipType = NonNullable<GraphEdge["relationship_type"]>;

const DIRECTED: ReadonlySet<string> = new Set(["prerequisite", "builds_on", "part_of"]);

// Spacing. A concept is a mark up to 46 across with a caption under it of up
// to 18 characters, about 100 wide at 10.5px.
/** Centre to centre, two concepts side by side: their captions do not meet. */
export const SPACE_X = 106;
/** Centre to centre, one concept above another: the upper caption clears the lower mark. */
export const SPACE_Y = 66;
/**
 * Plans are made with heights stretched by this much, so keeping concepts
 * `SPACE_X` apart there keeps them `SPACE_X` apart side by side on screen,
 * `SPACE_Y` apart one above the other, and an ellipse between the two.
 */
const STRETCH = SPACE_X / SPACE_Y;
/** A link's length (while planning): a little over the least room two concepts keep. */
const LINK = SPACE_X * 1.18;
/** A course root's links run this many links long, varied by concept, so they never read as a wheel's spokes. */
const SPOKE_LENGTH = { min: 1, max: 1.55 } as const;
/** The course root links to at most this many concepts. */
export const MAX_SPOKES = 6;
/**
 * No concept sits nearer its course root than this, on screen: room for the
 * root's mark (radius 28, `COURSE_NODE_R`) and course code, and a concept's
 * mark and caption beside them.
 */
export const ROOT_ROOM = 100;
/** How far a concept's mark and caption reach from its centre. */
export const CONCEPT_REACH = { x: 56, up: 26, down: 42 } as const;
/** How far a course root's mark (radius 28) and course code under it reach from its centre. */
export const ROOT_REACH = { x: 48, up: 32, down: 50 } as const;
/** Space kept between two courses' boxes when several share the canvas. */
export const COURSE_MARGIN = 48;
/**
 * The shape (width over height, on screen) each course is turned toward: a
 * little wider than tall, like most windows the graph opens in, but not so
 * wide that one course overflows a dashboard panel. Fixed, not taken from
 * the window, so resizing the window never re-plans a course.
 */
const COURSE_ASPECT = 1.4;
/** The turns tried, in planning space, when turning a course toward that shape. */
const TURNS = 12;
/** Room per concept, packed as closely as they may sit (planning space): a hexagon's worth. */
const CELL = (Math.sqrt(3) / 2) * SPACE_X * SPACE_X;
/**
 * The lobes a course grows into, as [harmonic, least, most] share of its
 * radius. Each course draws its own amounts and turns from its id, so no two
 * grow the same shape, and the same course always grows the same one.
 */
const LOBES: ReadonlyArray<readonly [number, number, number]> = [
  [2, 0.16, 0.32],
  [3, 0.08, 0.18],
  [4, 0.03, 0.08],
];
/**
 * How far to one side of the body a course grows, as a share of the room
 * its other concepts need: the group grows lopsided, never a disc round the
 * body. (The root moves into the group's middle afterwards: `centreRoot`.)
 */
const GROW_LEAN = 0.6;
/**
 * How far from the middle of its concepts the course root may be put, as a
 * share of their mean distance from that middle: it takes the roomiest spot
 * within that.
 */
const CENTRE_REACH = 0.4;

// The work, bounded: the distance layout costs the square of a group's size
// each round, so a very large group gets fewer rounds.
const STRESS_ROUNDS = 120;
const MDS_ROUNDS = 120;
/** A group up to this size gets every round; past it, rounds fall with the square of its size. */
const FULL_WORK = 160;
/** Rounds of letting a plan settle: links pull, crowding pushes. */
const SETTLE_ROUNDS = 40;
/** While settling, concepts closer than this (planning space) crowd each other. */
const CROWD = SPACE_X * 1.1;
const CROWD_PUSH = 0.06;
const LINK_PULL = 0.15;
/** The most rounds of the last pass that keeps concepts apart (it stops once nothing needs to move). */
const SPACING_ROUNDS = 400;
/** Rounds of place trading; a large course gets fewer. */
const UNTANGLE_ROUNDS = 16;
const UNTANGLE_LARGE = 400;

type Pt = { x: number; y: number };
/** Where a course's marks and captions reach, relative to its course root. */
export type Box = { minX: number; minY: number; maxX: number; maxY: number };
/** The box of a course root with no concepts. */
const ROOT_BOX: Box = Object.freeze({ minX: -ROOT_REACH.x, minY: -ROOT_REACH.up, maxX: ROOT_REACH.x, maxY: ROOT_REACH.down });

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

/** Plain string order, the same everywhere (no locale). */
const byId = (a: string, b: string) => (a < b ? -1 : a > b ? 1 : 0);

/** A 32-bit FNV-1a hash. */
function hashOf(s: string): number {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

/** A number in [0, 1) fixed by `s`: the plan's only source of variety, so a graph always gets the same plan. */
const unitOf = (s: string) => hashOf(s) / 4294967296;

/**
 * The concepts a course root links to, at most `max`: its starting concepts,
 * the biggest strands first. Where concepts are joined by prerequisite /
 * builds_on / part_of links, these are the ones nothing leads into that lead
 * somewhere; a group joined only by `related` links starts at its
 * most-linked concept; a concept with no links starts a group of its own.
 * Ties go to more concepts downstream, then more links, then id.
 */
export function startingConcepts(ids: readonly string[], edges: readonly GraphEdge[], max = MAX_SPOKES): string[] {
  const index = new Map(ids.map((id, i) => [id, i]));
  const parent = ids.map((_, i) => i);
  const find = (i: number): number => {
    while (parent[i] !== i) {
      parent[i] = parent[parent[i]];
      i = parent[i];
    }
    return i;
  };
  const linkCount = new Map<string, number>();
  const into = new Map<string, number>();
  const outOf = new Map<string, string[]>();
  const directedFrom: string[] = [];
  for (const e of edges) {
    const a = index.get(e.source);
    const b = index.get(e.target);
    if (a == null || b == null || a === b) continue;
    parent[find(a)] = find(b);
    linkCount.set(e.source, (linkCount.get(e.source) ?? 0) + 1);
    linkCount.set(e.target, (linkCount.get(e.target) ?? 0) + 1);
    if (isDirected(e)) {
      directedFrom.push(e.source);
      into.set(e.target, (into.get(e.target) ?? 0) + 1);
      if (!outOf.has(e.source)) outOf.set(e.source, []);
      outOf.get(e.source)!.push(e.target);
    }
  }
  const directedGroups = new Set(directedFrom.map((id) => find(index.get(id)!)));
  const groups = new Map<number, string[]>();
  ids.forEach((id, i) => {
    const g = find(i);
    if (!groups.has(g)) groups.set(g, []);
    groups.get(g)!.push(id);
  });
  const downstream = (id: string) => {
    const seen = new Set<string>();
    const stack = [...(outOf.get(id) ?? [])];
    while (stack.length) {
      const next = stack.pop()!;
      if (seen.has(next) || next === id) continue;
      seen.add(next);
      stack.push(...(outOf.get(next) ?? []));
    }
    return seen.size;
  };
  const links = (id: string) => linkCount.get(id) ?? 0;
  const starts: Array<{ id: string; size: number; below: number; links: number }> = [];
  for (const [g, members] of groups) {
    if (directedGroups.has(g)) {
      for (const id of members) {
        if (!into.get(id) && outOf.has(id)) starts.push({ id, size: members.length, below: downstream(id), links: links(id) });
      }
    } else {
      const id = members.reduce((best, m) =>
        links(m) > links(best) || (links(m) === links(best) && m < best) ? m : best,
      );
      starts.push({ id, size: members.length, below: 0, links: links(id) });
    }
  }
  starts.sort((p, q) => q.size - p.size || q.below - p.below || q.links - p.links || byId(p.id, q.id));
  return starts.slice(0, Math.max(0, max)).map((s) => s.id);
}

/** Neighbours with the length of the link to each. */
type Adjacency = Array<Array<[number, number]>>;

/** Rounds for a group of `count`: all of them up to FULL_WORK, fewer past it, never under ten. */
const roundsFor = (rounds: number, count: number) =>
  Math.max(10, Math.round(rounds * Math.min(1, (FULL_WORK / Math.max(1, count)) ** 2)));

/** Shortest-path lengths between every two nodes of a weighted graph (Dijkstra from each, on a binary heap). */
function allPairs(count: number, adj: Adjacency): Float64Array {
  const D = new Float64Array(count * count).fill(Infinity);
  const heap: Array<[number, number]> = [];
  const push = (item: [number, number]) => {
    heap.push(item);
    for (let i = heap.length - 1; i > 0; ) {
      const up = (i - 1) >> 1;
      if (heap[up][0] <= heap[i][0]) break;
      [heap[up], heap[i]] = [heap[i], heap[up]];
      i = up;
    }
  };
  const pop = (): [number, number] => {
    const top = heap[0];
    const last = heap.pop()!;
    if (heap.length) {
      heap[0] = last;
      for (let i = 0; ; ) {
        const l = 2 * i + 1;
        const r = l + 1;
        let low = i;
        if (l < heap.length && heap[l][0] < heap[low][0]) low = l;
        if (r < heap.length && heap[r][0] < heap[low][0]) low = r;
        if (low === i) break;
        [heap[low], heap[i]] = [heap[i], heap[low]];
        i = low;
      }
    }
    return top;
  };
  for (let s = 0; s < count; s++) {
    const row = s * count;
    D[row + s] = 0;
    push([0, s]);
    while (heap.length) {
      const [d, u] = pop();
      if (d > D[row + u]) continue;
      for (const [v, w] of adj[u]) {
        if (d + w < D[row + v]) {
          D[row + v] = d + w;
          push([d + w, v]);
        }
      }
    }
  }
  return D;
}

/** Two-dimensional classical MDS of a distance matrix, by power iteration from a seeded start. */
function classicalMds(count: number, D: Float64Array, seed: string): { x: Float64Array; y: Float64Array } {
  const x = new Float64Array(count);
  const y = new Float64Array(count);
  if (count < 2) return { x, y };
  // Double-centred squared distances.
  const B = new Float64Array(count * count);
  const rowMean = new Float64Array(count);
  let mean = 0;
  for (let i = 0; i < count; i++) {
    let sum = 0;
    for (let j = 0; j < count; j++) {
      const d2 = D[i * count + j] ** 2;
      B[i * count + j] = d2;
      sum += d2;
    }
    rowMean[i] = sum / count;
    mean += sum;
  }
  mean /= count * count;
  for (let i = 0; i < count; i++) {
    for (let j = 0; j < count; j++) B[i * count + j] = -0.5 * (B[i * count + j] - rowMean[i] - rowMean[j] + mean);
  }
  const rounds = roundsFor(MDS_ROUNDS, count);
  const axis = (against: Float64Array | null, salt: string) => {
    const v = Float64Array.from({ length: count }, (_, i) => unitOf(`${seed}|${salt}|${i}`) - 0.5);
    const w = new Float64Array(count);
    let length = 0;
    for (let r = 0; r < rounds; r++) {
      if (against) {
        let dot = 0;
        for (let i = 0; i < count; i++) dot += v[i] * against[i];
        for (let i = 0; i < count; i++) v[i] -= dot * against[i];
      }
      let norm = 0;
      for (let i = 0; i < count; i++) {
        let sum = 0;
        for (let j = 0; j < count; j++) sum += B[i * count + j] * v[j];
        w[i] = sum;
        norm += sum * sum;
      }
      norm = Math.sqrt(norm);
      if (norm < 1e-9) break;
      length = norm;
      for (let i = 0; i < count; i++) v[i] = w[i] / norm;
    }
    return { v, length };
  };
  const first = axis(null, "x");
  const second = axis(first.v, "y");
  const sx = Math.sqrt(first.length);
  const sy = Math.sqrt(second.length);
  for (let i = 0; i < count; i++) {
    x[i] = first.v[i] * sx;
    // A hair of seeded sideways room, so a group that is one straight line
    // (a chain) can still bend away from it.
    y[i] = second.v[i] * sy + (unitOf(`${seed}|bend|${i}`) - 0.5) * LINK * 0.02;
  }
  return { x, y };
}

/** Stress majorization by localized updates (Gansner, Koren and North, 2004); node `fixed` stays put. */
function stressMajorize(count: number, D: Float64Array, x: Float64Array, y: Float64Array, fixed: number) {
  const rounds = roundsFor(STRESS_ROUNDS, count);
  for (let r = 0; r < rounds; r++) {
    for (let i = 0; i < count; i++) {
      if (i === fixed) continue;
      let sx = 0;
      let sy = 0;
      let sw = 0;
      for (let j = 0; j < count; j++) {
        const d = D[i * count + j];
        if (j === i || !(d > 0) || !Number.isFinite(d)) continue;
        const w = 1 / (d * d);
        const ex = x[i] - x[j];
        const ey = y[i] - y[j];
        const dist = Math.hypot(ex, ey);
        // From exactly on top of each other, step off to the side.
        sx += w * (x[j] + (dist > 1e-9 ? (d * ex) / dist : d));
        sy += w * (y[j] + (dist > 1e-9 ? (d * ey) / dist : 0));
        sw += w;
      }
      if (sw > 0) {
        x[i] = sx / sw;
        y[i] = sy / sw;
      }
    }
  }
}

/** How wide a group of `count` concepts is, packed as closely as they may sit, with room for a course root. */
const radiusFor = (count: number, rooted: boolean) =>
  Math.sqrt((count * CELL) / Math.PI + (rooted ? ROOT_ROOM * ROOT_ROOM * STRETCH : 0));

/**
 * A connected group laid out by graph distance, `anchor` on the origin:
 * neighbours a link apart, strands running out from what they hang off.
 * Distances past the group's own width count as that width, so a strand
 * longer than the group is wide folds back on itself.
 */
function layoutByDistance(count: number, adj: Adjacency, seed: string, anchor: number, rooted: boolean) {
  const D = allPairs(count, adj);
  const cap = 2 * radiusFor(count - (rooted ? 1 : 0), rooted);
  for (let k = 0; k < D.length; k++) if (Number.isFinite(D[k]) && D[k] > cap) D[k] = cap;
  const { x, y } = classicalMds(count, D, seed);
  const ax = x[anchor];
  const ay = y[anchor];
  for (let i = 0; i < count; i++) {
    x[i] -= ax;
    y[i] -= ay;
  }
  stressMajorize(count, D, x, y, anchor);
  return { x, y };
}

/**
 * Turn a plan round the course root (planning space, where turning keeps
 * every spacing) to whichever of `TURNS` turns gives it, on screen, the shape
 * nearest `COURSE_ASPECT`, counting a bigger box against it a little.
 */
function turnToward(n: number, X: Float64Array, Y: Float64Array, rooted: boolean) {
  if (n < 2) return;
  const tried = Array.from({ length: TURNS }, (_, k) => {
    const turn = (k * Math.PI) / TURNS;
    const c = Math.cos(turn);
    const s = Math.sin(turn);
    const box = boxOf(
      Array.from({ length: n }, (_, i) => ({ x: X[i] * c - Y[i] * s, y: (X[i] * s + Y[i] * c) / STRETCH })),
      rooted,
    );
    const w = box.maxX - box.minX;
    const h = box.maxY - box.minY;
    return { turn, miss: Math.abs(Math.log(w / h / COURSE_ASPECT)), area: w * h };
  });
  const least = Math.min(...tried.map((t) => t.area));
  const score = (t: (typeof tried)[number]) => t.miss + 0.5 * Math.log(t.area / least);
  const best = tried.reduce((b, t) => (score(t) < score(b) - 1e-9 ? t : b));
  const c = Math.cos(best.turn);
  const s = Math.sin(best.turn);
  for (let i = 0; i < n; i++) {
    const x = X[i];
    const y = Y[i];
    X[i] = x * c - y * s;
    Y[i] = x * s + y * c;
  }
}

/**
 * Calls `visit(i, j)` once for every two of the first `count` points that
 * were closer than `reach` when the call began (a grid of `reach`-sized
 * cells, so the work grows with the count, not its square).
 */
function eachClosePair(
  count: number,
  x: Float64Array,
  y: Float64Array,
  reach: number,
  visit: (i: number, j: number) => void,
) {
  const cells = new Map<string, number[]>();
  const cellOf = (v: number) => Math.floor(v / reach);
  for (let i = 0; i < count; i++) {
    const k = `${cellOf(x[i])},${cellOf(y[i])}`;
    let list = cells.get(k);
    if (!list) cells.set(k, (list = []));
    list.push(i);
  }
  const close: Array<[number, number]> = [];
  for (let i = 0; i < count; i++) {
    const cx = cellOf(x[i]);
    const cy = cellOf(y[i]);
    for (let gx = cx - 1; gx <= cx + 1; gx++) {
      for (let gy = cy - 1; gy <= cy + 1; gy++) {
        for (const j of cells.get(`${gx},${gy}`) ?? []) {
          if (j > i && Math.hypot(x[j] - x[i], y[j] - y[i]) < reach) close.push([i, j]);
        }
      }
    }
  }
  close.sort((p, q) => p[0] - q[0] || p[1] - q[1]);
  for (const [i, j] of close) visit(i, j);
}

/**
 * One pass of keeping concepts apart: any two closer than `SPACE_X`
 * (planning space) step apart, half each, and any concept within
 * `ROOT_ROOM` of the course root (on screen) steps straight out from it.
 */
function keepApart(n: number, X: Float64Array, Y: Float64Array, rooted: boolean): boolean {
  let moved = false;
  eachClosePair(n, X, Y, SPACE_X, (i, j) => {
    const ex = X[j] - X[i];
    const ey = Y[j] - Y[i];
    const d = Math.hypot(ex, ey);
    if (d >= SPACE_X) return;
    moved = true;
    // From exactly on top of each other, side by side.
    const ux = d > 1e-9 ? ex / d : 1;
    const uy = d > 1e-9 ? ey / d : 0;
    const push = (SPACE_X - d) / 2;
    X[i] -= ux * push;
    Y[i] -= uy * push;
    X[j] += ux * push;
    Y[j] += uy * push;
  });
  if (!rooted) return moved;
  for (let i = 0; i < n; i++) {
    const sx = X[i];
    const sy = Y[i] / STRETCH;
    const d = Math.hypot(sx, sy);
    if (d >= ROOT_ROOM) continue;
    moved = true;
    if (d < 1e-9) {
      X[i] = ROOT_ROOM;
      Y[i] = 0;
      continue;
    }
    X[i] = (sx * ROOT_ROOM) / d;
    Y[i] = ((sy * ROOT_ROOM) / d) * STRETCH;
  }
  return moved;
}

/**
 * Trade places, two concepts at a time, while that shortens their links
 * (squared, so one long link counts for more than two short ones; a course
 * root's links count too, the root staying put). Shorter links cross less,
 * so a course reads as strands rather than a knot. Pairs are tried in index
 * order, so the same graph always ends up arranged the same way.
 */
function untangle(
  n: number,
  X: Float64Array,
  Y: Float64Array,
  links: ReadonlyArray<readonly [number, number]>,
  spokes: readonly number[],
) {
  const linked: number[][] = Array.from({ length: n }, () => []);
  for (const [a, b] of links) {
    linked[a].push(b);
    linked[b].push(a);
  }
  const spoke = new Uint8Array(n);
  for (const i of spokes) spoke[i] = 1;
  /** What `i`'s links measure (squared) with it at (px, py) and `other` at (ox, oy). */
  const strain = (i: number, px: number, py: number, other: number, ox: number, oy: number) => {
    let sum = spoke[i] ? px * px + py * py : 0;
    for (const m of linked[i]) {
      const mx = m === other ? ox : X[m];
      const my = m === other ? oy : Y[m];
      sum += (px - mx) ** 2 + (py - my) ** 2;
    }
    return sum;
  };
  const rounds = n > UNTANGLE_LARGE ? 3 : UNTANGLE_ROUNDS;
  for (let round = 0; round < rounds; round++) {
    let traded = false;
    for (let a = 0; a < n; a++) {
      for (let b = a + 1; b < n; b++) {
        // Two concepts with no links have nothing to gain from each other.
        if (!linked[a].length && !linked[b].length && !spoke[a] && !spoke[b]) continue;
        const now = strain(a, X[a], Y[a], b, X[b], Y[b]) + strain(b, X[b], Y[b], a, X[a], Y[a]);
        const then = strain(a, X[b], Y[b], b, X[a], Y[a]) + strain(b, X[a], Y[a], a, X[b], Y[b]);
        if (then >= now - 1) continue;
        [X[a], X[b]] = [X[b], X[a]];
        [Y[a], Y[b]] = [Y[b], Y[a]];
        traded = true;
      }
    }
    if (!traded) break;
  }
}

/**
 * Move the course root into the middle of its concepts, leaving them where
 * they are: to the spot within `CENTRE_REACH` of their middle (on screen)
 * with the most room round it, counting distance from the middle against a
 * spot. The plan is then re-centred on it. Any concept nearer it than
 * `ROOT_ROOM` steps out to make room in the spacing pass that follows, which
 * moves little else.
 */
function centreRoot(n: number, X: Float64Array, Y: Float64Array) {
  if (n < 3) return;
  let mx = 0;
  let my = 0;
  for (let i = 0; i < n; i++) {
    mx += X[i];
    my += Y[i] / STRETCH;
  }
  mx /= n;
  my /= n;
  let spread = 0;
  for (let i = 0; i < n; i++) spread += Math.hypot(X[i] - mx, Y[i] / STRETCH - my);
  const reach = (CENTRE_REACH * spread) / n;
  const step = Math.max(4, reach / 12);
  let best = { x: mx, y: my, score: -Infinity };
  for (let gx = -reach; gx <= reach + 1e-9; gx += step) {
    for (let gy = -reach; gy <= reach + 1e-9; gy += step) {
      const off = Math.hypot(gx, gy);
      if (off > reach + 1e-9) continue;
      let room = Infinity;
      for (let i = 0; i < n; i++) room = Math.min(room, Math.hypot(X[i] - mx - gx, Y[i] / STRETCH - my - gy));
      // Room counts up to what the root needs; past that, nearer the middle wins.
      const score = Math.min(room, ROOT_ROOM) - 0.5 * off;
      if (score > best.score + 1e-9) best = { x: mx + gx, y: my + gy, score };
    }
  }
  for (let i = 0; i < n; i++) {
    X[i] -= best.x;
    Y[i] -= best.y * STRETCH;
  }
}

/**
 * Let the plan settle: links pull toward their length, a course root's links
 * keep theirs, and concepts that crowd each other push apart, each round a
 * little less far, keeping apart as they go.
 */
function settle(
  n: number,
  X: Float64Array,
  Y: Float64Array,
  links: ReadonlyArray<readonly [number, number]>,
  spokes: readonly number[],
  rooted: boolean,
) {
  const spokeLength = spokes.map((i) => [i, Math.hypot(X[i], Y[i])] as const);
  const dx = new Float64Array(n);
  const dy = new Float64Array(n);
  for (let r = 0; r < SETTLE_ROUNDS; r++) {
    const most = SPACE_X * 0.25 * (1 - r / SETTLE_ROUNDS) + 0.5;
    dx.fill(0);
    dy.fill(0);
    eachClosePair(n, X, Y, CROWD, (i, j) => {
      const ex = X[j] - X[i];
      const ey = Y[j] - Y[i];
      const d = Math.hypot(ex, ey);
      const ux = d > 1e-9 ? ex / d : 1;
      const uy = d > 1e-9 ? ey / d : 0;
      const f = CROWD_PUSH * (CROWD - d);
      dx[i] -= ux * f;
      dy[i] -= uy * f;
      dx[j] += ux * f;
      dy[j] += uy * f;
    });
    for (const [a, b] of links) {
      const ex = X[b] - X[a];
      const ey = Y[b] - Y[a];
      const d = Math.hypot(ex, ey) || 1e-9;
      const f = LINK_PULL * (d - LINK);
      dx[a] += (ex / d) * f;
      dy[a] += (ey / d) * f;
      dx[b] -= (ex / d) * f;
      dy[b] -= (ey / d) * f;
    }
    for (const [i, length] of spokeLength) {
      const d = Math.hypot(X[i], Y[i]) || 1e-9;
      const f = LINK_PULL * (d - length);
      dx[i] -= (X[i] / d) * f;
      dy[i] -= (Y[i] / d) * f;
    }
    for (let i = 0; i < n; i++) {
      const d = Math.hypot(dx[i], dy[i]);
      const k = d > most ? most / d : 1;
      X[i] += dx[i] * k;
      Y[i] += dy[i] * k;
    }
    keepApart(n, X, Y, rooted);
  }
}

/** The connected groups of a graph, each in index order, in order of their first node. */
function groupsOf(count: number, adj: Adjacency): number[][] {
  const group = new Int32Array(count).fill(-1);
  const groups: number[][] = [];
  for (let start = 0; start < count; start++) {
    if (group[start] >= 0) continue;
    const members: number[] = [];
    const queue = [start];
    group[start] = groups.length;
    for (let k = 0; k < queue.length; k++) {
      const u = queue[k];
      members.push(u);
      for (const [v] of adj[u]) {
        if (group[v] < 0) {
          group[v] = groups.length;
          queue.push(v);
        }
      }
    }
    groups.push(members.sort((a, b) => a - b));
  }
  return groups;
}

/** One course's plan: each concept's seat and which concepts its root links to. */
export type CoursePlan = {
  /** Concept id → its seat, on screen, relative to the course root (or, with no root, to the group's middle). */
  seats: Map<string, Pt>;
  /** The concepts the course root links to. */
  spokes: ReadonlySet<string>;
  /** Where the course's marks and captions reach, relative to its root. */
  box: Box;
};

/**
 * Plan one course: its concepts' seats round its root (`rootId`, or none for
 * concepts whose course root is not in the graph, which are planned round
 * the middle of their own group).
 */
export function planCourse(conceptIds: readonly string[], edges: readonly GraphEdge[], rootId: string | null): CoursePlan {
  const ids = [...new Set(conceptIds)].sort(byId);
  const n = ids.length;
  const rooted = rootId != null;
  const key = rootId ?? "";
  if (!n) return { seats: new Map(), spokes: new Set(), box: { ...ROOT_BOX } };

  const index = new Map(ids.map((id, i) => [id, i]));
  // Links between the course's own concepts, once each, in a fixed order.
  const seen = new Set<number>();
  const links: Array<[number, number]> = [];
  for (const e of edges) {
    const a = index.get(e.source);
    const b = index.get(e.target);
    if (a == null || b == null || a === b) continue;
    const lo = Math.min(a, b);
    const hi = Math.max(a, b);
    if (seen.has(lo * n + hi)) continue;
    seen.add(lo * n + hi);
    links.push([lo, hi]);
  }
  links.sort((p, q) => p[0] - q[0] || p[1] - q[1]);

  // The course root, when there is one, is node n.
  const count = n + (rooted ? 1 : 0);
  const adj: Adjacency = Array.from({ length: count }, () => []);
  for (const [a, b] of links) {
    adj[a].push([b, LINK]);
    adj[b].push([a, LINK]);
  }
  const spokeIds = rooted ? startingConcepts(ids, edges) : [];
  const spokes = spokeIds.map((id) => index.get(id)!);
  for (const i of spokes) {
    const length = LINK * (SPOKE_LENGTH.min + (SPOKE_LENGTH.max - SPOKE_LENGTH.min) * unitOf(`${key}|spoke|${ids[i]}`));
    adj[n].push([i, length]);
    adj[i].push([n, length]);
  }

  // The body is what is joined to the root (with no root, the group with the
  // most-linked concept); every other group grows round it.
  const groups = groupsOf(count, adj);
  let hub = n;
  if (!rooted) {
    hub = 0;
    for (let i = 1; i < n; i++) if (adj[i].length > adj[hub].length) hub = i;
  }
  const body = groups.find((g) => g.includes(hub))!;
  const rest = groups
    .filter((g) => g !== body)
    .sort((p, q) => q.length - p.length || unitOf(`${key}|group|${ids[p[0]]}`) - unitOf(`${key}|group|${ids[q[0]]}`));

  const X = new Float64Array(count);
  const Y = new Float64Array(count);
  {
    const local = new Map(body.map((u, i) => [u, i]));
    const ladj: Adjacency = body.map((u) => adj[u].filter(([v]) => local.has(v)).map(([v, w]) => [local.get(v)!, w] as [number, number]));
    const { x, y } = layoutByDistance(body.length, ladj, `${key}|body`, local.get(hub)!, rooted);
    // Which way up is drawn from the course, so courses are not all mirror images.
    const flip = unitOf(`${key}|flip`) < 0.5 ? -1 : 1;
    body.forEach((u, i) => {
      X[u] = x[i];
      Y[u] = y[i] * flip;
    });
  }

  if (rest.length) growInto(n, X, Y, body, rest, adj, ids, key, rooted);
  untangle(n, X, Y, links, spokes);
  settle(n, X, Y, links, spokes, rooted);
  turnToward(n, X, Y, rooted);
  // After the turn, so moving the root never turns the course another way.
  if (rooted) centreRoot(n, X, Y);
  for (let r = 0; r < SPACING_ROUNDS && keepApart(n, X, Y, rooted); r++);

  // Back to the screen's proportions, round the root (or the group's middle).
  let shiftX = 0;
  let shiftY = 0;
  if (!rooted) {
    const box = boxOf(ids.map((_, i) => ({ x: X[i], y: Y[i] / STRETCH })), false);
    shiftX = -(box.minX + box.maxX) / 2;
    shiftY = -(box.minY + box.maxY) / 2;
  }
  const seats = new Map(ids.map((id, i) => [id, { x: X[i] + shiftX, y: Y[i] / STRETCH + shiftY }]));
  return { seats, spokes: new Set(spokeIds), box: boxOf(seats.values(), rooted) };
}

/** Where marks and captions at `seats` reach, with the course root's own at the origin when `rooted`. */
function boxOf(seats: Iterable<Pt>, rooted: boolean): Box {
  const box = rooted ? { ...ROOT_BOX } : { minX: Infinity, minY: Infinity, maxX: -Infinity, maxY: -Infinity };
  for (const p of seats) {
    box.minX = Math.min(box.minX, p.x - CONCEPT_REACH.x);
    box.maxX = Math.max(box.maxX, p.x + CONCEPT_REACH.x);
    box.minY = Math.min(box.minY, p.y - CONCEPT_REACH.up);
    box.maxY = Math.max(box.maxY, p.y + CONCEPT_REACH.down);
  }
  return Number.isFinite(box.minX) ? box : { minX: 0, minY: 0, maxX: 0, maxY: 0 };
}

/**
 * Set each group down, biggest first, in the nearest room free for all of
 * it: nearest the body's middle by a lobed measure the course draws from its
 * id, so the course grows lobes rather than rings. A group keeps its own
 * shape, tried at six turns. Free means every concept at least `SPACE_X`
 * from every other (planning space) and clear of the course root.
 */
function growInto(
  n: number,
  X: Float64Array,
  Y: Float64Array,
  body: readonly number[],
  rest: readonly number[][],
  adj: Adjacency,
  ids: readonly string[],
  key: string,
  rooted: boolean,
) {
  const lobes = LOBES.map(([k, least, most]) => ({
    k,
    amount: least + (most - least) * unitOf(`${key}|lobe|${k}`),
    turn: unitOf(`${key}|lobe-turn|${k}`) * Math.PI,
  }));
  const shape = (angle: number) => 1 + lobes.reduce((sum, l) => sum + l.amount * Math.cos(l.k * (angle - l.turn)), 0);
  let mx = 0;
  let my = 0;
  for (const u of body) {
    mx += X[u];
    my += Y[u];
  }
  mx /= body.length;
  my /= body.length;
  let extent = 0;
  for (const u of body) extent = Math.max(extent, Math.hypot(X[u] - mx, Y[u] - my));
  const restCount = rest.reduce((sum, g) => sum + g.length, 0);
  const lean = unitOf(`${key}|lean`) * Math.PI * 2;
  const leanBy = GROW_LEAN * radiusFor(restCount, false);
  const gx0 = mx + Math.cos(lean) * leanBy;
  const gy0 = my + Math.sin(lean) * leanBy;
  const reach = extent + leanBy + 2 * radiusFor(restCount, false) + 2 * SPACE_X;

  // Candidate spots: a fine lattice round the body, cheapest first.
  const step = SPACE_X / 3;
  const rowStep = step * (Math.sqrt(3) / 2);
  const spots: Array<{ x: number; y: number; cost: number }> = [];
  const rows = Math.ceil(reach / rowStep);
  const cols = Math.ceil(reach / step);
  for (let j = -rows; j <= rows; j++) {
    for (let i = -cols; i <= cols; i++) {
      const x = mx + i * step + (j & 1 ? step / 2 : 0);
      const y = my + j * rowStep;
      const dx = x - gx0;
      const dy = y - gy0;
      const cost = Math.hypot(dx, dy) / shape(Math.atan2(dy, dx)) + unitOf(`${key}|spot|${i},${j}`) * 0.02 * SPACE_X;
      spots.push({ x, y, cost });
    }
  }
  spots.sort((p, q) => p.cost - q.cost);

  // Who is where, for checking room.
  const cells = new Map<string, number[]>();
  const cellOf = (v: number) => Math.floor(v / SPACE_X);
  const occupy = (u: number) => {
    const k = `${cellOf(X[u])},${cellOf(Y[u])}`;
    let list = cells.get(k);
    if (!list) cells.set(k, (list = []));
    list.push(u);
  };
  for (const u of body) if (u < n) occupy(u);
  const free = (x: number, y: number) => {
    if (rooted && Math.hypot(x, y / STRETCH) < ROOT_ROOM + 4) return false;
    const cx = cellOf(x);
    const cy = cellOf(y);
    for (let gx = cx - 1; gx <= cx + 1; gx++) {
      for (let gy = cy - 1; gy <= cy + 1; gy++) {
        for (const u of cells.get(`${gx},${gy}`) ?? []) if (Math.hypot(X[u] - x, Y[u] - y) < SPACE_X) return false;
      }
    }
    return true;
  };

  // A spot that has no room for one concept never will again: lone concepts,
  // which come last, start looking past those.
  let firstFree = 0;
  for (const g of rest) {
    let gx: Float64Array = new Float64Array(1);
    let gy: Float64Array = new Float64Array(1);
    if (g.length > 1) {
      const local = new Map(g.map((u, i) => [u, i]));
      const ladj: Adjacency = g.map((u) => adj[u].filter(([v]) => local.has(v)).map(([v, w]) => [local.get(v)!, w] as [number, number]));
      ({ x: gx, y: gy } = layoutByDistance(g.length, ladj, `${key}|group|${ids[g[0]]}`, 0, false));
      let cx = 0;
      let cy = 0;
      for (let i = 0; i < g.length; i++) {
        cx += gx[i];
        cy += gy[i];
      }
      for (let i = 0; i < g.length; i++) {
        gx[i] -= cx / g.length;
        gy[i] -= cy / g.length;
      }
    }
    const offset = unitOf(`${key}|group-turn|${ids[g[0]]}`) * Math.PI;
    const turns = g.length > 1 ? Array.from({ length: 6 }, (_, k) => offset + (k * Math.PI) / 3) : [0];
    let placed = false;
    for (let s = g.length > 1 ? 0 : firstFree; s < spots.length && !placed; s++) {
      const spot = spots[s];
      for (const turn of turns) {
        const c = Math.cos(turn);
        const sn = Math.sin(turn);
        let fits = true;
        for (let i = 0; i < g.length && fits; i++) fits = free(spot.x + gx[i] * c - gy[i] * sn, spot.y + gx[i] * sn + gy[i] * c);
        if (!fits) {
          if (g.length === 1 && s === firstFree) firstFree += 1;
          continue;
        }
        g.forEach((u, i) => {
          X[u] = spot.x + gx[i] * c - gy[i] * sn;
          Y[u] = spot.y + gx[i] * sn + gy[i] * c;
          occupy(u);
        });
        placed = true;
        break;
      }
    }
    if (!placed) {
      // No room left in reach (never expected): past its edge, to be pushed clear.
      g.forEach((u, i) => {
        X[u] = mx + reach + i * SPACE_X;
        Y[u] = my;
        occupy(u);
      });
    }
  }
}

/** Course plans already made, by what they were made from (most recent last). */
const PLANS = new Map<string, CoursePlan>();
const PLANS_KEPT = 32;

/**
 * `planCourse`, remembered: a course is planned again only when its concepts
 * or the links between them change, not each time the window is measured.
 */
function coursePlan(ids: readonly string[], edges: readonly GraphEdge[], rootId: string | null): CoursePlan {
  const members = new Set(ids);
  const own = edges
    .filter((e) => members.has(e.source) && members.has(e.target))
    .map((e) => `${e.source}\u0000${e.target}\u0000${e.relationship_type ?? ""}`)
    .sort(byId);
  const key = `${rootId ?? ""}\u0001${[...members].sort(byId).join("\u0000")}\u0001${own.join("\u0001")}`;
  const kept = PLANS.get(key);
  if (kept) {
    PLANS.delete(key);
    PLANS.set(key, kept);
    return kept;
  }
  const plan = planCourse(ids, edges, rootId);
  PLANS.set(key, plan);
  if (PLANS.size > PLANS_KEPT) PLANS.delete(PLANS.keys().next().value!);
  return plan;
}

/**
 * Where courses sit, relative to the middle of the canvas, given each one's
 * box: whichever arrangement shows them largest in a `width` × `height`
 * window. Courses go in rows, left to right and top to bottom, each row
 * centred, `COURSE_MARGIN` between boxes; with rows of unequal length the
 * shorter goes on top, which leaves the window's top corners (where a host
 * puts its course key and zoom buttons) clear. When several arrangements fit
 * at full size, the one shaped most like the window wins.
 */
export function packCourses(boxes: readonly Box[], width: number, height: number): Pt[] {
  return arrangeCourses(boxes, width, height)?.spots ?? [];
}

/** One way of setting courses out in rows: where each sits, the rows' lengths, and how large it shows. */
type Arrangement = { spots: Pt[]; lengths: number[]; scale: number; fill: number };

/**
 * The arrangement `packCourses` settles on. `cap` is the largest size worth
 * showing the courses at: arrangements that reach it are told apart by how
 * well they fill the window.
 */
function arrangeCourses(boxes: readonly Box[], width: number, height: number, cap = 1): Arrangement | null {
  const count = boxes.length;
  if (!count) return null;
  const w = Math.max(width, 1);
  const h = Math.max(height, 1);
  let best: Arrangement | null = null;
  for (let rows = 1; rows <= count; rows++) {
    const spots: Pt[] = [];
    const lengths = rowLengths(count, rows);
    let top = 0;
    let spanX = 0;
    let k = 0;
    for (const length of lengths) {
      const row = boxes.slice(k, k + length);
      const rowHeight = Math.max(...row.map((b) => b.maxY - b.minY));
      const rowWidth = row.reduce((sum, b) => sum + b.maxX - b.minX, 0) + COURSE_MARGIN * (length - 1);
      let left = -rowWidth / 2;
      for (const b of row) {
        spots.push({ x: left - b.minX, y: top + (rowHeight - (b.maxY - b.minY)) / 2 - b.minY });
        left += b.maxX - b.minX + COURSE_MARGIN;
      }
      spanX = Math.max(spanX, rowWidth);
      top += rowHeight + COURSE_MARGIN;
      k += length;
    }
    const spanY = top - COURSE_MARGIN;
    for (const s of spots) s.y -= spanY / 2;
    const scale = Math.min(w / spanX, h / spanY, cap);
    const fill = Math.min((spanX * scale) / w, (spanY * scale) / h);
    if (!best || scale > best.scale + 1e-9 || (scale > best.scale - 1e-9 && fill > best.fill + 1e-9)) {
      best = { spots, lengths, scale, fill };
    }
  }
  return best;
}

/**
 * `packCourses` for a graph that opens zoomed out, with room to spare: the
 * same rows, but the room left over is shared out evenly (between the
 * courses of a row, between the rows, and at the edges) rather than left
 * round courses gathered in the middle. Courses never come nearer each other
 * than `COURSE_MARGIN`.
 */
export function spreadCourses(boxes: readonly Box[], width: number, height: number): Pt[] {
  const best = arrangeCourses(boxes, width, height);
  if (!best) return [];
  const rows: Box[][] = [];
  let k = 0;
  for (const length of best.lengths) {
    rows.push(boxes.slice(k, k + length));
    k += length;
  }
  const heights = rows.map((row) => Math.max(...row.map((b) => b.maxY - b.minY)));
  const tall = heights.reduce((sum, v) => sum + v, 0);
  const gapY = Math.max(COURSE_MARGIN, (Math.max(height, 1) - tall) / (rows.length + 1));
  const spots: Pt[] = [];
  let top = -(tall + gapY * (rows.length - 1)) / 2;
  rows.forEach((row, r) => {
    const wide = row.reduce((sum, b) => sum + b.maxX - b.minX, 0);
    const gapX = Math.max(COURSE_MARGIN, (Math.max(width, 1) - wide) / (row.length + 1));
    let left = -(wide + gapX * (row.length - 1)) / 2;
    for (const b of row) {
      spots.push({ x: left - b.minX, y: top + (heights[r] - (b.maxY - b.minY)) / 2 - b.minY });
      left += b.maxX - b.minX + gapX;
    }
    top += heights[r] + gapY;
  });
  return spots;
}

/**
 * `count` courses over `rows` rows, as evenly as they divide, longer and
 * shorter rows alternating. A shorter row goes on top when it can.
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

export type RadialPlan = {
  /** Course root id → where it sits. */
  centers: Map<string, Pt>;
  /**
   * Concept id → its seat: the root it sits round (null: the canvas middle),
   * how far from it and at what angle, and whether the root links to it.
   */
  orbit: Map<string, { rootId: string | null; radius: number; angle: number; spoke: boolean }>;
  /** Each course's planned box, relative to its root; a course with no concepts has its root's. */
  boxes: Map<string | null, Box>;
};

/**
 * Plan every course and where each sits. Concepts whose course root is not
 * in the node set (a quiz neighbourhood fragment) are planned round the
 * middle of the canvas instead.
 *
 * `openZoom` under 1 plans for a graph that opens zoomed out that far (the
 * tree, which opens with its concept labels faded out): the window then
 * shows `1 / openZoom` times as much each way, and the graph is planned to
 * be spread evenly through all of it. Concepts are set further apart, by up
 * to `1 / openZoom` (as far apart on the opening screen as they are planned
 * at full size, and no further), and the courses share out whatever room is
 * still left (`spreadCourses`). A graph too large for that is planned as at
 * full size and opens further out still.
 */
export function planRadial(
  nodes: GraphNode[],
  conceptEdges: GraphEdge[],
  width: number,
  height: number,
  openZoom = 1,
): RadialPlan {
  const roots = nodes.filter((n) => n.is_subject_root);
  const rootByCourse = new Map(roots.map((r) => [r.course_id, r.id]));
  const groups = new Map<string | null, string[]>();
  const rootOf = new Map<string, string | null>();
  for (const n of nodes) {
    if (n.is_subject_root) continue;
    const key = rootByCourse.get(n.course_id) ?? null;
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key)!.push(n.id);
    rootOf.set(n.id, key);
  }

  const courses = new Map<string | null, CoursePlan>();
  const boxes: RadialPlan["boxes"] = new Map();
  for (const [rootId, ids] of groups) {
    const course = coursePlan(ids, conceptEdges, rootId);
    courses.set(rootId, course);
    boxes.set(rootId, { ...course.box });
  }
  for (const r of roots) if (!boxes.has(r.id)) boxes.set(r.id, { ...ROOT_BOX });

  // Opening zoomed out: the room the window shows then, less a margin at its
  // edges, and how much further apart the concepts can sit and still fit it.
  const spread = openZoom > 0 && openZoom < 1;
  const roomX = Math.max(width / (spread ? openZoom : 1) - 2 * COURSE_MARGIN, 1);
  const roomY = Math.max(height / (spread ? openZoom : 1) - 2 * COURSE_MARGIN, 1);
  let grow = 1;
  if (spread) {
    const whole = roots.length ? roots.map((r) => boxes.get(r.id)!) : [...boxes.values()];
    grow = Math.max(1, arrangeCourses(whole, roomX, roomY, 1 / openZoom)?.scale ?? 1);
    if (grow > 1) {
      for (const [rootId, course] of courses) {
        boxes.set(rootId, boxOf([...course.seats.values()].map((p) => ({ x: p.x * grow, y: p.y * grow })), rootId != null));
      }
    }
  }

  const orbit: RadialPlan["orbit"] = new Map();
  for (const [id, rootId] of rootOf) {
    const course = courses.get(rootId)!;
    const seat = course.seats.get(id)!;
    orbit.set(id, {
      rootId,
      radius: Math.hypot(seat.x, seat.y) * grow,
      angle: Math.atan2(seat.y, seat.x),
      spoke: course.spokes.has(id),
    });
  }

  const rootBoxes = roots.map((r) => boxes.get(r.id)!);
  const spots = spread ? spreadCourses(rootBoxes, roomX, roomY) : packCourses(rootBoxes, width, height);
  const centers: RadialPlan["centers"] = new Map(
    roots.map((r, i) => [r.id, { x: width / 2 + spots[i].x, y: height / 2 + spots[i].y }]),
  );
  return { centers, orbit, boxes };
}

/**
 * The course's own links: one to each concept its root links to (a few of
 * its starting concepts, `startingConcepts`). Built here rather than taken
 * from /api/graph, whose spokes go to every concept.
 */
export function courseLinks(plan: RadialPlan): GraphEdge[] {
  const out: GraphEdge[] = [];
  for (const [id, o] of plan.orbit) {
    if (o.rootId && o.spoke) out.push({ source: o.rootId, target: id, strength: 0.5, relationship_type: "part_of" });
  }
  return out;
}

/** Where the planned layout reaches, with room for marks and labels. */
export function planBounds(plan: RadialPlan, width: number, height: number) {
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  const grow = (x: number, y: number, reach: { x: number; up: number; down: number }) => {
    minX = Math.min(minX, x - reach.x);
    maxX = Math.max(maxX, x + reach.x);
    minY = Math.min(minY, y - reach.up);
    maxY = Math.max(maxY, y + reach.down);
  };
  for (const c of plan.centers.values()) grow(c.x, c.y, ROOT_REACH);
  for (const o of plan.orbit.values()) {
    const c = (o.rootId && plan.centers.get(o.rootId)) || { x: width / 2, y: height / 2 };
    grow(c.x + Math.cos(o.angle) * o.radius, c.y + Math.sin(o.angle) * o.radius, CONCEPT_REACH);
  }
  return Number.isFinite(minX) ? { minX, minY, maxX, maxY } : null;
}

type Positioned = { id: string; x?: number; y?: number; vx?: number; vy?: number };

/**
 * A custom d3 force pulling each concept toward its planned place round its
 * course root's CURRENT position (so dragging a course drags its concepts
 * along): firmly to its distance from the root, gently to its angle.
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
