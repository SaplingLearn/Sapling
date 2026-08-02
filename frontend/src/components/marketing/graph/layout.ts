/**
 * Layout + entry-path math for the landing graph demo (#344).
 *
 * Deterministic by construction — no randomness, no time input. The E2E lane
 * parks the animation and asserts against the laid-out frame, so the same graph
 * and viewport must always produce the same coordinates.
 */
import { COURSE_GRAPHS, type CourseGraph } from './courseGraphs';

export interface Point {
  x: number;
  y: number;
}

/** An SVG `viewBox`, in user units. */
export interface ViewBox {
  x: number;
  y: number;
  w: number;
  h: number;
}

/**
 * Labels render in JetBrains Mono, whose advance width is 600/1000 em, and the
 * face's cap height / descender depth are ~0.73 / ~0.25 em. These are font
 * facts, shared by the viewBox fit below and by `layout.test.ts`'s independent
 * bounds sweep, so the two can't drift apart on a rounding tweak.
 */
export const MONO_ADVANCE_EM = 0.6;
export const LABEL_CAP_EM = 0.73;
export const LABEL_DESCENDER_EM = 0.25;

/**
 * Everything the demo needs to draw itself at one viewport class, in SVG user
 * units. The `<svg>` is `width: 100%` up to a max-width, so the rendered CSS
 * size of *every* dimension below is `value * (renderedWidth / fit.w)`.
 *
 * `w` / `h` are the LAYOUT box: they exist only to place the centre that
 * `radialLayout` orbits (`w / 2`, `h / 2`) and to keep the desktop geometry
 * byte-identical to what this branch was designed against. They are NOT what
 * gets rendered — see `fit` below.
 *
 * The two views are picked apart by `useIsMobile()` in the component. Keeping
 * them as data (rather than a pile of ternaries at each call site) is what lets
 * `layout.test.ts` sweep the entry animation against *both* views and prove
 * nothing leaves frame.
 */
export interface GraphGeometry {
  /** Layout-box width, user units. Sets the orbit centre, not the frame. */
  w: number;
  /** Layout-box height, user units. Sets the orbit centre, not the frame. */
  h: number;
  /** Radius of the outermost ring — the layout's whole spatial budget. */
  maxRadius: number;
  /** Label font-size, user units. */
  font: number;
  /** Root-node circle radius, user units. */
  rootR: number;
  /** Non-root node circle radius, user units. */
  nodeR: number;
  /** Gap between a node's circle edge and its label baseline, either way up. */
  labelGap: number;
  /**
   * Whether the root's label sits ABOVE its circle instead of below it
   * (#344 visual 4). Per view, because it is a geometry question, not a taste
   * one — see `labelBaselineY`.
   */
  rootLabelAbove: boolean;
  /** Width of the paper-coloured halo stroked under label text. */
  labelHalo: number;
  /** Edge stroke width, user units. */
  edgeW: number;
  /** Breathing room added on every side of the fitted content box. */
  fitPad: number;
}

/** A geometry plus the viewBox derived from it. This is what the demo renders. */
export interface GraphView extends GraphGeometry {
  /**
   * The rendered `viewBox`, fitted to the actual drawn content across every
   * fixture (#344 visual 3). Derived, never hand-written — see `fitViewBox`.
   */
  fit: ViewBox;
}

function clamp01(t: number): number {
  return t < 0 ? 0 : t > 1 ? 1 : t;
}

export function easeOutCubic(t: number): number {
  const c = clamp01(t);
  return 1 - Math.pow(1 - c, 3);
}

/**
 * The BFS spanning tree of the UNDIRECTED graph, rooted at `graph.rootId`.
 *
 * `DemoNode.children` is deliberately NOT consulted: it is dead data that
 * disagrees with `edges` (nothing reads it but the fixtures' own prose), and
 * trusting it would put a node's position and its drawn edges on two different
 * sources of truth. Every edge is undirected here because the demo draws them
 * undirected.
 *
 * The tree governs POSITION only. `AssemblingGraph` still draws every entry in
 * `graph.edges`, cross-edges included — `cs-sorting → cs-complexity` runs from
 * the canopy's left tip back down to the middle shoot, closing a triangle, and
 * is a big part of why the picture reads as a graph rather than a sprig.
 */
function spanningTree(graph: CourseGraph): {
  depth: Map<string, number>;
  parent: Map<string, string>;
} {
  const adj = new Map<string, string[]>();
  for (const e of graph.edges) {
    adj.set(e.source, [...(adj.get(e.source) ?? []), e.target]);
    adj.set(e.target, [...(adj.get(e.target) ?? []), e.source]);
  }

  const depth = new Map<string, number>([[graph.rootId, 0]]);
  const parent = new Map<string, string>();
  const queue = [graph.rootId];
  while (queue.length) {
    const cur = queue.shift()!;
    for (const nxt of adj.get(cur) ?? []) {
      if (!depth.has(nxt)) {
        depth.set(nxt, depth.get(cur)! + 1);
        parent.set(nxt, cur);
        queue.push(nxt);
      }
    }
  }
  return { depth, parent };
}

/**
 * Number of nodes in each node's subtree of the spanning tree, itself included.
 *
 * Only used to decide WHICH depth-1 seat a child gets (see `fanSeats`). Walking
 * the depths from the outside in means a node's children are always counted
 * before the node is added to its own parent, so one pass is enough.
 */
function subtreeSizes(
  graph: CourseGraph,
  depth: Map<string, number>,
  parent: Map<string, string>,
): Map<string, number> {
  const size = new Map(graph.nodes.map((n) => [n.id, 1]));
  const deepestFirst = [...graph.nodes]
    .map((n) => n.id)
    .sort((a, b) => (depth.get(b) ?? 0) - (depth.get(a) ?? 0));
  for (const id of deepestFirst) {
    const p = parent.get(id);
    if (p) size.set(p, (size.get(p) ?? 1) + (size.get(id) ?? 1));
  }
  return size;
}

/**
 * The seat angles of the depth-1 fan, left to right, as angles from 3 o'clock.
 * SVG angles run clockwise (y grows downward), so −π is 9 o'clock, −π/2 is 12
 * and 0 is 3 — i.e. the open interval (−π, 0) is the UPWARD half-plane.
 *
 * `count` children take the `count` interior gridlines of a (count + 1)-way
 * split of that half-plane: `−π + (seat + 1) · π/(count + 1)`. For three
 * children that is 45° / 90° / 135°, a canopy; for one it is straight up.
 *
 * WHY THE INTERIOR GRIDLINES and not slice centres (`(seat + ½) · π/count`,
 * which would spread the same three children over 30° / 90° / 150°). Two
 * reasons, both measured across all three fixtures × both views:
 *
 * - the horizon. Slice centres put the outermost child `π/(2·count)` off the
 *   horizontal, which for a wide fan is a nearly flat arm whose second segment
 *   runs level with the root; the gridlines put it `π/(count + 1)` off, which
 *   is strictly further from the horizon for every `count > 1` and is why the
 *   no-horizontal invariant below holds with room to spare (measured |sin| =
 *   0.707 against a 0.5 floor).
 * - shape. At 30° the settled drawing is 0.35 tall for every unit wide — a flat
 *   candelabra. At 45° it is 0.51–0.56, which is the canopy the section's
 *   "watch it grow" headline is describing.
 *
 * THE INVARIANT THIS KEEPS. No child ever lands on the horizontal axis through
 * the root: the seat angles are `−π + k·π/(count+1)` for `k` in `1…count`, so
 * `|sin θ| = sin(k·π/(count+1))`, which is zero only at `k = 0` or `k =
 * count+1` — both outside the range. The previous wave proved the same property
 * for a full-circle ring phased by an odd multiple of `π/(2·count)`; this is
 * the half-plane version of it, and it is strictly stronger (the closest
 * approach is `sin(π/(count+1))`, never worse than the old `sin(π/(2·count))`).
 */
function fanAngle(seat: number, count: number): number {
  return -Math.PI + ((seat + 1) * Math.PI) / (count + 1);
}

/**
 * The order the depth-1 seats are handed out in: OUTSIDE-IN — leftmost,
 * rightmost, next-leftmost, next-rightmost, … — with the biggest subtrees
 * going first (see the caller).
 *
 * The outer seats have open sky beyond them; the inner seats are hemmed in by a
 * sibling on each side, so the branches that carry the most nodes get the room.
 * With the shipped fixtures (two children carrying a grandchild, one leaf) that
 * seats the two deep arms symmetrically about the vertical and leaves the leaf
 * as a short central shoot — the sprout silhouette.
 *
 * The alternative — handing seats out left to right — was measured and
 * rejected: it puts one two-step arm on the vertical axis and the one-step leaf
 * beside it, so the drawing leans (its base lands 13% of the frame width off
 * the centre, against 2% here) and cs210's `cs-sorting → cs-complexity`
 * cross-edge runs straight through the middle node's label (−7.3 units at the
 * desktop type scale; on the phone no combination of radius, type scale, dot
 * size and label gap clears it while the labels still render at 11 CSS px).
 */
function fanSeats(count: number): number[] {
  const seats: number[] = [];
  let lo = 0;
  let hi = count - 1;
  while (lo <= hi) {
    seats.push(lo);
    if (lo !== hi) seats.push(hi);
    lo += 1;
    hi -= 1;
  }
  return seats;
}

/**
 * A SAPLING. The root sits at the bottom-centre of the drawing; depth-1 fans
 * upward across the half-plane above it at radius `ring`; every deeper node is
 * placed at radius `ring` from ITS OWN PARENT, inside a wedge centred on the
 * direction that parent itself grew in. Siblings share (and subdivide) the
 * wedge. Because every depth-1 heading points upward, so does everything below
 * it: the whole structure fans up.
 *
 * WHAT THIS WAVE CHANGED, and nothing else: the ANGULAR DOMAIN. The BFS
 * spanning tree and the parent-relative placement are exactly as the previous
 * wave left them, and every edge in `graph.edges` is still drawn, cross-edges
 * included. What moved is that depth-1 used to be spread around the FULL circle
 * with the root at the frame's centre, so the tree grew one arm up and two
 * down — an inverted Y, or a root system. The product is called Sapling and the
 * section headline is "Pick a course. Watch it grow."; a drawing that grows
 * downward is the wrong picture, and no amount of ring phasing fixes a full
 * circle.
 *
 * WHY THE ROOT IS NOT AT `(width/2, height/2)` ANY MORE. That point is the
 * centre `helixEntry` spirals around and the point `fitViewBox` fits its frame
 * about — the sweep is very nearly a disc centred there. Leaving the root on it
 * while growing upward would put the whole drawing in the disc's top half and
 * reserve the bottom half for nothing: measured, the settled box lands 15.7% of
 * the frame height off centre and fills 0.41 of it (against 0.53 here), and the
 * `<svg>` grows to 676px. So the skeleton is laid out with the root at the
 * origin and then translated as a rigid body until ITS OWN bounding box is
 * centred on `(width/2, height/2)`. The root ends up at the bottom-centre of
 * the content, the sweep stays centred on the drawing, and the frame comes out
 * centred on it too (measured ≤ 3.2% off on either axis, every fixture, both
 * views).
 *
 * `maxRadius` is the spatial budget: `ring = maxRadius / maxDepth`, so a chain
 * of `maxDepth` collinear steps spans exactly it. A node whose siblings push it
 * off its parent's outward direction sits INSIDE that radius, so `maxRadius` is
 * an upper bound rather than an exact outer ring. Its default is unchanged
 * (`min(w, h)/2 − 48`) so every existing caller keeps working, but both shipped
 * views pass it explicitly — the binding constraints are the fitted frame, the
 * label clearances and the phone's legibility floor, none of which
 * `min(w, h)/2 − pad` can express.
 *
 * Deterministic by construction: no randomness, no clock, no DOM read.
 */
export function radialLayout(
  graph: CourseGraph,
  width: number,
  height: number,
  maxRadius: number = Math.min(width, height) / 2 - 48,
): Map<string, Point> {
  const { depth, parent } = spanningTree(graph);

  const byDepth = new Map<number, string[]>();
  // Iterate graph.nodes (declaration order), not the Map, so sibling ordering
  // is stable regardless of BFS visit order.
  for (const n of graph.nodes) {
    const d = depth.get(n.id) ?? 0;
    byDepth.set(d, [...(byDepth.get(d) ?? []), n.id]);
  }

  const maxDepth = Math.max(...byDepth.keys(), 1);
  const ring = maxRadius / maxDepth;

  /** Laid out with the root at the origin; translated to the frame at the end. */
  const out = new Map<string, Point>();
  /** The direction this node GREW in — the axis its own wedge is built on. */
  const heading = new Map<string, number>();
  /** Angular span this node's subtree owns, subdivided among its children. */
  const wedge = new Map<string, number>();

  for (const d of [...byDepth.keys()].sort((a, b) => a - b)) {
    const ids = byDepth.get(d)!;

    // Depth 0 is the root — plus, defensively, anything the BFS never reached.
    if (d === 0) {
      for (const id of ids) out.set(id, { x: 0, y: 0 });
      continue;
    }

    if (d === 1) {
      const gap = Math.PI / (ids.length + 1);
      const seats = fanSeats(ids.length);
      const size = subtreeSizes(graph, depth, parent);
      // Biggest subtree first, ties in declaration order (Array#sort is stable),
      // so the deep arms take the outer seats.
      const seated = [...ids].sort((a, b) => (size.get(b) ?? 1) - (size.get(a) ?? 1));
      seated.forEach((id, i) => {
        const a = fanAngle(seats[i], ids.length);
        out.set(id, { x: Math.cos(a) * ring, y: Math.sin(a) * ring });
        heading.set(id, a);
        wedge.set(id, gap);
      });
      continue;
    }

    const siblings = new Map<string, string[]>();
    for (const id of ids) {
      const p = parent.get(id)!;
      siblings.set(p, [...(siblings.get(p) ?? []), id]);
    }
    for (const [p, kids] of siblings) {
      const anchor = out.get(p)!;
      // The parent's own outward direction. The fallback is the bearing from
      // the root, which is where the root sits while this loop runs.
      const base = heading.get(p) ?? Math.atan2(anchor.y, anchor.x);
      const span = wedge.get(p) ?? Math.PI;
      const slice = span / kids.length;
      kids.forEach((id, i) => {
        // Centre of this child's slice — a lone child therefore lands exactly
        // on the parent's outward direction, i.e. collinear with it.
        const a = base - span / 2 + (i + 0.5) * slice;
        const q = { x: anchor.x + Math.cos(a) * ring, y: anchor.y + Math.sin(a) * ring };
        out.set(id, q);
        heading.set(id, a);
        wedge.set(id, slice);
      });
    }
  }

  // Rigid translation: centre the skeleton's own bounding box on the layout
  // box's centre, which is the point the entry sweep spirals around. See the
  // doc comment above for why this is not "put the root at the centre".
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  for (const p of out.values()) {
    minX = Math.min(minX, p.x);
    minY = Math.min(minY, p.y);
    maxX = Math.max(maxX, p.x);
    maxY = Math.max(maxY, p.y);
  }
  const dx = width / 2 - (minX + maxX) / 2;
  const dy = height / 2 - (minY + maxY) / 2;

  const placed = new Map<string, Point>();
  for (const [id, p] of out) placed.set(id, { x: p.x + dx, y: p.y + dy });
  return placed;
}

/**
 * How far *inside* its target radius a node starts. The offset from the centre
 * is scaled by `1 - (1 - e) * ENTRY_CONTRACTION`, i.e. 0.55× at t=0 rising to
 * exactly 1× at t=1.
 *
 * This used to be a *stretch* (`1 + (1 - e) * 0.9`, so 1.9× at t=0), which is
 * the #344-review-#4 bug: swept against the real desktop layout (centre 450,280;
 * outer ring at radius 232) the outer nodes reached y = 693 — 133px below the
 * 560 viewBox edge — and crossed back in at opacity ≈ 0.5, so the visitor
 * watched them get chopped off by the `<svg>` viewport mid-assembly. Because
 * the spiral now only ever *contracts*, every point of the sweep lies inside
 * the disc of radius |target − centre|. `layout.test.ts` pins that as an
 * explicit bounds sweep over every fixture × every view.
 *
 * It reads better too: nodes now grow outward from the root rather than flying
 * in from off-frame.
 */
const ENTRY_CONTRACTION = 0.45;

/**
 * Position along the helical entry path. `t` runs 0 → 1.
 *
 * The node spirals outward from near the centre: its offset from the centre is
 * rotated by a decreasing angle and contracted by a shrinking factor, while
 * scale and opacity rise. At t=1 every term collapses and the node sits exactly
 * on `target`, so the animation has no seam where it hands off to the static
 * layout.
 */
export function helixEntry(
  target: Point,
  centre: Point,
  t: number,
  turns = 1.5,
): { x: number; y: number; scale: number; opacity: number } {
  const e = easeOutCubic(t);
  const dx = target.x - centre.x;
  const dy = target.y - centre.y;

  const angle = (1 - e) * turns * Math.PI * 2;
  const radiusScale = 1 - (1 - e) * ENTRY_CONTRACTION;
  const cos = Math.cos(angle);
  const sin = Math.sin(angle);

  return {
    x: centre.x + (dx * cos - dy * sin) * radiusScale,
    y: centre.y + (dx * sin + dy * cos) * radiusScale,
    scale: 0.35 + 0.65 * e,
    opacity: e,
  };
}

/** Half the drawn width of a label, halo included. Labels are `middle`-anchored. */
export function labelHalfWidth(label: string, geom: GraphGeometry): number {
  return (label.length * MONO_ADVANCE_EM * geom.font) / 2 + geom.labelHalo / 2;
}

/**
 * Where a node's label baseline sits, relative to the node's drawn centre.
 *
 * BOTH shipped views now put the root's label BELOW its circle, and that is a
 * consequence of the root moving to the base of the drawing. "Above" used to be
 * the open half — it was the direction with no graph in it. Under the upward
 * fan it is the direction the whole plant grows in: the course code lands on
 * the stem running from the root up to its middle child, where the halo has to
 * cut the edge in two to stay legible, and it eats 20 units off the settled
 * box's height (aspect 0.562 → 0.53, and the frame does not shrink with it, so
 * the dead band grows). Below the root there is nothing but the frame edge, and
 * the code reads as a caption at the ground line. Measured, below clears its
 * nearest neighbour by 30.14 units on desktop and 5.40 on the phone; above
 * clears by 9.83 and 2.71.
 *
 * `rootLabelAbove` is kept — it is part of `GraphGeometry`'s shape, it is what
 * makes the choice a per-view geometry question rather than a hard-coded taste
 * one, and `layout.test.ts` still exercises both branches — but no shipped view
 * sets it today.
 *
 * Shared with `fitViewBox` and `layout.test.ts` so the frame can never be
 * fitted to a label position the component doesn't actually use.
 */
export function labelBaselineY(
  geom: GraphGeometry,
  isRoot: boolean,
  y: number,
  r: number,
): number {
  return isRoot && geom.rootLabelAbove ? y - r - geom.labelGap : y + r + geom.labelGap;
}

/** Vertical extent of the drawn label text, halo included. */
function labelVerticalExtent(
  geom: GraphGeometry,
  isRoot: boolean,
  y: number,
  r: number,
): { top: number; bottom: number } {
  const baseline = labelBaselineY(geom, isRoot, y, r);
  return {
    top: baseline - geom.font * LABEL_CAP_EM - geom.labelHalo / 2,
    bottom: baseline + geom.font * LABEL_DESCENDER_EM + geom.labelHalo / 2,
  };
}

/**
 * Sampling density of the entry sweep when fitting the frame.
 *
 * Finer than the 400 steps `layout.test.ts` sweeps, so the test can never land
 * between two samples and find a point the fit didn't see. In practice the
 * extremes sit at the sweep's endpoints and at broad interior maxima, so the
 * two agree to ~0.01 units — the `fitPad` swallows the rest with room over.
 */
const FIT_STEPS = 512;

/**
 * The tightest box that contains everything the demo ever draws — for every
 * fixture, for every frame of the entry animation.
 *
 * #344 visual 3: the demo shipped with a hardcoded `viewBox="0 0 900 560"`
 * stretched across a ~1184px container, so it reserved ~737px of height while
 * the content clustered near the centre and the whole outer band of the box
 * stayed permanently empty. The frame is now measured off the content instead.
 *
 * THE THING TO NOT GET WRONG: fit to the HELIX SWEEP, not to the settled node
 * positions. `helixEntry` rotates a node up to 1.5 turns around the centre on
 * the way in, so every outer node passes through every direction on its way to
 * rest. Under the upward fan that gap is WIDER still than it was under the
 * downward tree, because a canopy is a wide, short object inside a circular
 * sweep: on desktop the settled drawing spans 284.3 units of height while the
 * sweep spans 513.6, so a box fitted to the settled positions would clip 125.8
 * units off the top and 103.6 off the bottom — 150 and 124 CSS px at the
 * rendered cap, in plain view. That exact bug was found and fixed once already
 * on this branch (#344 review #4). The phone numbers are 82.9 and 69.6, against
 * 63.6 and 73.5 before. `layout.test.ts` sweeps `t` across
 * the full range to keep it fixed, and pins the overshoot itself so a
 * settled-fit implementation fails outright.
 *
 * Fitted ONCE across all three fixtures rather than per graph: the three share
 * a topology and differ only in label widths, so a per-graph fit would produce
 * three slightly different boxes and — because the `<svg>` is `h-auto` — the
 * section would change height every time a visitor clicked a course chip. A
 * jumping section is a worse defect than a few units of slack on the side where
 * some other course happens to have the longest word.
 *
 * The box is snapped OUTWARD to whole units so the rendered `viewBox` attribute
 * stays readable and rounding can never shave the frame.
 */
export function fitViewBox(graphs: CourseGraph[], geom: GraphGeometry): ViewBox {
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;

  const centre = { x: geom.w / 2, y: geom.h / 2 };

  for (const graph of graphs) {
    const points = radialLayout(graph, geom.w, geom.h, geom.maxRadius);
    for (const n of graph.nodes) {
      const p = points.get(n.id);
      if (!p) continue;
      const isRoot = n.id === graph.rootId;
      const r = isRoot ? geom.rootR : geom.nodeR;
      const half = labelHalfWidth(n.label, geom);

      for (let i = 0; i <= FIT_STEPS; i++) {
        const h = helixEntry(p, centre, i / FIT_STEPS);
        const dotR = r * h.scale;
        const label = labelVerticalExtent(geom, isRoot, h.y, r);

        minX = Math.min(minX, h.x - dotR, h.x - half);
        maxX = Math.max(maxX, h.x + dotR, h.x + half);
        minY = Math.min(minY, h.y - dotR, label.top);
        maxY = Math.max(maxY, h.y + dotR, label.bottom);
      }
    }
  }

  const x = Math.floor(minX - geom.fitPad);
  const y = Math.floor(minY - geom.fitPad);
  return {
    x,
    y,
    w: Math.ceil(maxX + geom.fitPad) - x,
    h: Math.ceil(maxY + geom.fitPad) - y,
  };
}

/** The `viewBox` attribute string for a fitted box. */
export function viewBoxAttr(box: ViewBox): string {
  return `${box.x} ${box.y} ${box.w} ${box.h}`;
}

function withFit(geom: GraphGeometry): GraphView {
  return { ...geom, fit: fitViewBox(COURSE_GRAPHS, geom) };
}

/**
 * Retuned for the upward fan. Frame `161 17 603 534`, against `165 48 541 498`
 * for the downward radial tree, `185 33 526 516` for the ring layout before it,
 * and the `0 0 900 560` the demo shipped with.
 *
 * The component caps the rendered width (`md:max-w-[720px]`), so at the cap the
 * graph draws at 1.194 user units per CSS px: 16.7px labels, 33.4px concept
 * dots, a 62px root, and a **637.6px-tall `<svg>` — 25px SHORTER** than the
 * downward tree's 662.8 and 99px shorter than the 737px the fixed box reserved.
 *
 * WHY `maxRadius` LEFT 232, i.e. why it is no longer `radialLayout`'s
 * inscribed-circle default. Under the upward fan the drawing wraps its own
 * centre much more tightly than a full-circle spread does, so the same budget
 * produced a 460-unit frame and a 19px type scale. The budget is now solved,
 * not inherited, against three constraints that the layout box cannot express:
 *
 * - the rendered type scale (720 / `fit.w`), which sets label and dot sizes;
 * - the label clearances, which improve as the ring grows against a fixed type
 *   size — 320 buys 30.14 units (36 CSS px) on the worst pair, against the
 *   8.80 units (6.6 px) the downward tree shipped;
 * - the shape assertions, which are scale-free.
 *
 * The composition it buys, measured on cs210: the drawing is 506 × 284 units
 * (604 × 339 CSS px) inside a 603 × 534 frame, centred to within 2.8% of the
 * width and 2.1% of the height. It fills **0.839 of the frame's width** against
 * the downward tree's 0.828 (ma242 0.916, sm275 0.881), and 0.53 of its height.
 *
 * The height share is the one number that did not improve, and it is worth
 * being precise about why: `fitViewBox` fits the frame to the ENTRY SWEEP, and
 * the sweep is very nearly a disc, so the frame is very nearly square whatever
 * the drawing does. Dead vertical space is therefore ≈ (drawing width −
 * drawing height) / 2 for any layout, and a canopy is by definition wider than
 * tall. Measured: 149 CSS px of band above and below, against 145 for the
 * downward tree — a wash. Making that band small needs a drawing with aspect
 * ≈ 1, which is neither a canopy nor shorter (swept: a symmetric fan narrow
 * enough to fill the height renders a 683px section). The lever that would
 * actually shrink it is the sweep itself — `helixEntry`'s 1.5 turns — and that
 * is an animation change, out of this wave's scope.
 */
export const DESKTOP_VIEW: GraphView = withFit({
  w: 900,
  h: 560,
  maxRadius: 320,
  font: 14,
  rootR: 26,
  nodeR: 14,
  labelGap: 13,
  rootLabelAbove: false,
  labelHalo: 3,
  edgeW: 1.4,
  fitPad: 10,
});

/**
 * The phone view, and the breakpoint that gains the most from the upward fan.
 * Frame `-32 -25 443 365`; a ~332px content box (390 viewport − 48 of `px-6` −
 * the 10px scrollbar globals.css paints) renders it at 0.7494, so 16-unit
 * labels land at **11.99 CSS px**, concept dots at a **22.48px** diameter, and
 * the `<svg>` is **273.5px** tall. All three clear the E2E legibility gate
 * (≥11px labels, ≥20px dots, >260px tall), and all three are BETTER than the
 * downward tree's 11.23 / 20.85 / 285.5 on the two that were nearly lost.
 *
 * THE CONSTRAINT THAT WAS RAZOR-THIN AND NO LONGER IS. Labels hang below their
 * dots and are `middle`-anchored, so a 13-character label ("Vector Spaces",
 * "Distributions", "Central Limit") reaches 3.9·font units to each side of its
 * node. The downward tree put its two deep arms 120° apart, which forces one of
 * them to within 30° of the horizontal, so a child's dot landed inside its own
 * parent's label unless `0.866·ring > 3.9·font + labelHalo/2 + nodeR`; the
 * shipped geometry met that by **+1.23 units (0.99 CSS px)** and the label gate
 * by +0.23 CSS px, both inside the noise of whether Chromium paints a scrollbar
 * at that viewport.
 *
 * The fan changes the geometry that produces the number. Its two deep arms are
 * 90° apart and symmetric about the vertical, so the worst horizontal step is
 * `ring·sin 45°` on BOTH of them instead of `ring·sin 60°` on one and
 * `ring·sin 30°` on the other, and the crowded pair moves from "a child's dot
 * inside its parent's label" to "the middle shoot's label beside a depth-1
 * dot". Measured worst pair over all three fixtures: **+5.40 units = 4.05 CSS
 * px**, a 4× improvement, with the label gate now clearing by 0.99 CSS px
 * instead of 0.23.
 *
 * The window is still two-sided — the collision wants a bigger ring, the
 * legibility gate wants a smaller frame (`font · 332 / fit.w ≥ 11`) — and the
 * point below was picked by sweeping `maxRadius`, `font`, `rootR`, `nodeR` and
 * `labelGap` against BOTH ends plus the shape assertions, maximising the worst
 * normalised margin. `fitPad` stays at 2 (the fit's outward whole-unit snap
 * sits under it); everything else moved.
 */
export const MOBILE_VIEW: GraphView = withFit({
  w: 360,
  h: 300,
  maxRadius: 212,
  font: 16,
  rootR: 22,
  nodeR: 15,
  labelGap: 15,
  rootLabelAbove: false,
  labelHalo: 3.5,
  edgeW: 1.8,
  fitPad: 2,
});

/** Every view the demo can render in — the sweep target for the bounds test. */
export const GRAPH_VIEWS: GraphView[] = [DESKTOP_VIEW, MOBILE_VIEW];
