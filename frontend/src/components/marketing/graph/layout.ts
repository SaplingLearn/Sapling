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
 * `graph.edges`, cross-edges included — `cs-sorting → cs-complexity` closes a
 * triangle back to the top of the frame and is a big part of why the picture
 * reads as a graph rather than a star.
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
 * Where the depth-1 ring's FIRST node sits, as an angle from 3 o'clock. SVG
 * angles run clockwise (y grows downward), so −π/2 is 12 o'clock.
 *
 * THE INVARIANT, unchanged from the previous wave and for the same reason. The
 * ring starts a quarter of a slot FORWARD of 3 o'clock, so its angles are
 * `(4i + 1) · step/4` — ODD multiples of `step/4 = π/(2·count)`. An odd multiple
 * of `π/(2n)` is never a multiple of π (that would need `odd = 2kn`), so a ring
 * of ANY size lands no node on the horizontal axis through the centre. `−3` and
 * `+1` are both odd, so this is the same proof the `−3·step/4` rule carried;
 * the two differ only by one whole slot, i.e. by WHICH child gets which seat.
 *
 * WHY THE SEATS MOVED BY ONE. For count 3 the ring is 4, 8 and 12 o'clock
 * either way. What changed is that the layout below is now a tree: the two
 * children that carry subtrees (indices 0 and 1 in all three fixtures) grow a
 * second segment straight outward, and every label hangs BELOW its dot. Seated
 * at 4 and 8 o'clock those arms grow downward and their labels fall away from
 * the root; seated at 12 o'clock (the old `−3·step/4`) an arm grows straight up
 * and the drawing goes lopsided — measured, that phase puts the settled box
 * 10.4% of the frame off-centre and cannot be made collision-free at the phone
 * breakpoint at any radius (worst pair −2.7 units at `maxRadius` 200, still
 * negative). The childless third child takes the 12 o'clock seat, where its
 * label is the only object above the root.
 *
 * That does tie the composition to fixture declaration order — the third child
 * being the leaf. It is the same dependency the ring layout had, and it is
 * pinned by the collision suite rather than left to chance.
 */
function ringPhase(count: number): number {
  return (Math.PI * 2) / count / 4;
}

/**
 * A RADIAL TREE. Root at the centre; depth-1 spread evenly around the full
 * circle at radius `ring`; every deeper node placed at radius `ring` from ITS
 * OWN PARENT, inside a wedge centred on the direction from the centre to that
 * parent. Siblings share (and subdivide) the wedge.
 *
 * THE BUG THIS FIXES. The layout used to be global concentric RINGS: a node's
 * angle came from its index within its depth, so it had no relationship to
 * where its parent sat. With the shipped 6-node fixtures that scatters the
 * graph — `cs-sorting` (a child of `cs-arrays`) landed 171 units from its
 * parent on a ring of radius 232, `cs-trees` was flung to the opposite corner,
 * and the result read as a lopsided diagonal smear rather than a tree. Tuning
 * the ring angles cannot fix it: the previous wave swept them, moved the
 * aspect metric from 0.436 to 1.006, and made the composition visibly worse.
 * Every tree edge is now exactly one `ring` long — max 170.9 → 116.0 desktop,
 * mean 128.5 → 116.0 — because a child is placed off its parent, not off the
 * centre.
 *
 * `maxRadius` is the spatial budget: `ring = maxRadius / maxDepth`, so a chain
 * of `maxDepth` collinear steps lands exactly on it. A node whose siblings push
 * it off its parent's outward direction sits INSIDE that radius, so `maxRadius`
 * is an upper bound rather than an exact outer ring. It defaults to the old
 * inscribed-circle-minus-48 rule so every existing caller and test is
 * unchanged, but each view passes it explicitly: the binding constraint is the
 * *fitted* frame, not the layout box, and `min(w, h) / 2 - pad` can't express
 * that.
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

  const cx = width / 2;
  const cy = height / 2;
  const maxDepth = Math.max(...byDepth.keys(), 1);
  const ring = maxRadius / maxDepth;

  const out = new Map<string, Point>();
  /** Direction from the CENTRE to this node — the axis its own wedge is built on. */
  const heading = new Map<string, number>();
  /** Angular span this node's subtree owns, subdivided among its children. */
  const wedge = new Map<string, number>();

  for (const d of [...byDepth.keys()].sort((a, b) => a - b)) {
    const ids = byDepth.get(d)!;

    // Depth 0 is the root — plus, defensively, anything the BFS never reached.
    if (d === 0) {
      for (const id of ids) out.set(id, { x: cx, y: cy });
      continue;
    }

    if (d === 1) {
      const step = (Math.PI * 2) / ids.length;
      const phase = ringPhase(ids.length);
      ids.forEach((id, i) => {
        const a = i * step + phase;
        out.set(id, { x: cx + Math.cos(a) * ring, y: cy + Math.sin(a) * ring });
        heading.set(id, a);
        wedge.set(id, step);
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
      const base = heading.get(p) ?? Math.atan2(anchor.y - cy, anchor.x - cx);
      const span = wedge.get(p) ?? Math.PI * 2;
      const slice = span / kids.length;
      kids.forEach((id, i) => {
        // Centre of this child's slice — a lone child therefore lands exactly
        // on the parent's outward direction, i.e. collinear with the centre.
        const a = base - span / 2 + (i + 0.5) * slice;
        const q = { x: anchor.x + Math.cos(a) * ring, y: anchor.y + Math.sin(a) * ring };
        out.set(id, q);
        heading.set(id, Math.atan2(q.y - cy, q.x - cx));
        wedge.set(id, slice);
      });
    }
  }
  return out;
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
 * On DESKTOP the root's label stays above it (#344 visual 4). Both halves are
 * collision-free under the tree, and the numbers moved: measured across all
 * three fixtures, above clears by 8.80 units — the binding neighbour is the
 * cross-edge that runs from an 8 o'clock child up to the 12 o'clock one
 * (`ma-matrices → ma-eigen`, `sm-dist → sm-testing`) — and below by 31.24, in
 * the open wedge between the two downward arms. So "below" is now the roomier
 * half, where the ring layout made it the tighter one. It is a one-line flip if
 * the composition ever wants it; it is not taken here because 8.80 units is
 * 6.6 CSS px at the rendered cap, and because flipping it would leave
 * `rootLabelAbove` false in every shipped view — a flag and a branch with no
 * caller.
 *
 * On MOBILE it stays below, because there the geometry still forbids the
 * alternative outright. The childless third child sits `ring` straight above
 * the root with its own label hanging back down toward it, so an
 * above-the-root label only clears it when
 *
 *     ring ≥ rootR + nodeR + 2·labelGap + cap + descender
 *
 * — 84.1 units at the phone type scale, against an 81.5-unit ring. Measured,
 * "above" overlaps that label by 8.72 units; below clears everything by 14.53.
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
 * rest. Under the radial tree that gap is WIDER than it was under the rings,
 * because a tree is a wide object inside a circular sweep: on desktop the
 * settled drawing spans 280.5 units of height while the sweep spans 476.3, so a
 * box fitted to the settled positions would clip 91.1 units off the top and
 * 104.7 off the bottom — 121 and 139 CSS px at the rendered cap, in plain view.
 * That exact bug was found and fixed once already on this branch (#344 review
 * #4). The phone numbers are 63.6 and 73.5. `layout.test.ts` sweeps `t` across
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
 * Untouched by the tree rewrite: `maxRadius: 232` is still `radialLayout`'s old
 * default (`min(900, 560) / 2 - 48`), so the spatial budget, the type scale and
 * the dot sizes are exactly what this branch was designed and reviewed against.
 * Only the arrangement inside that budget changed, and the frame re-fitted
 * around it: `165 48 541 498`, against `185 33 526 516` for the ring layout,
 * `159 42 578 498` for the flat ring before that, and the `0 0 900 560` the
 * demo shipped with.
 *
 * The component caps the rendered width (`md:max-w-[720px]`), so at the cap the
 * graph draws at 1.331 user units per CSS px: 16.0px labels, 37.3px concept
 * dots, a 69px root, and a 663px-tall `<svg>` — 43px SHORTER than the ring
 * layout's 706px and 74px shorter than the 737px the fixed box reserved.
 *
 * The composition it buys, measured on cs210: the drawing is 448 × 281 units
 * (596 × 374 CSS px) inside a 541 × 498 frame, centred to within 18 units
 * horizontally and 7 vertically. It fills 83% of the frame's width against the
 * ring layout's 71%; it fills less of its height (56% against 73%) because a
 * three-branch tree is a wide object and the frame is fitted to a near-circular
 * entry sweep — see `fitViewBox`. That is the deliberate trade: symmetric
 * whitespace above and below a balanced drawing, rather than a taller drawing
 * whose children sit nowhere near their parents.
 */
export const DESKTOP_VIEW: GraphView = withFit({
  w: 900,
  h: 560,
  maxRadius: 232,
  font: 12,
  rootR: 26,
  nodeR: 14,
  labelGap: 16,
  rootLabelAbove: true,
  labelHalo: 3,
  edgeW: 1.4,
  fitPad: 10,
});

/**
 * The phone view, RETUNED for the tree — and the reason the retune was not
 * optional. Frame `-38 -11 414 356`; a ~332px content box (390 viewport − 48 of
 * `px-6` − the 10px scrollbar globals.css paints) renders it at 0.802, so
 * 14-unit labels land at 11.23 CSS px, concept dots at a 20.9px diameter, and
 * the `<svg>` is 285px tall — all three still over the E2E legibility gate
 * (≥11px labels, ≥20px dots, >260px tall), and all three tighter than the ring
 * layout's 12.8 / 25.5 / 301.
 *
 * WHY THE RING HAD TO GROW (132 → 163). Labels hang below their dots and are
 * `middle`-anchored, so a 13-character label ("Vector Spaces", "Distributions",
 * "Central Limit") is 3.9·font units wide on each side of its node. In a tree
 * the child of a depth-1 node sits `ring` away along that node's outward
 * direction, and with three children 120° apart the flattest arm is always 30°
 * off the horizontal — that is forced, not chosen: of two arms 120° apart, the
 * best achievable worst-case horizontal step is `ring·sin(60°)`. So the child's
 * dot lands inside its own parent's label unless
 *
 *   0.866 · ring  >  3.9 · font + labelHalo/2 + nodeR
 *
 * — `ring ≥ 76` at this type scale, against the 66 the ring layout used. At
 * `ring = 66` the overlap measures −13.1 units on ma242 and sm275.
 *
 * WHAT BOUNDS IT FROM ABOVE is the same E2E gate, through the fitted frame:
 * `fit.w ≈ 3.65·ring + 7.8·font + labelHalo + 2·fitPad`, and legibility needs
 * `font · 332 / fit.w ≥ 11`. The two brackets leave a window about 4 units of
 * `ring` wide; 81.5 (`maxRadius` 163, halved by `maxDepth`) sits in it with
 * +1.23 units on the worst label pair — up from the +0.80 the ring layout
 * shipped — and +0.23 CSS px on the label gate. `nodeR` drops 14 → 13 and
 * `fitPad` 10 → 2 to buy that window; both are spent directly on the two
 * constraints above, and `fitPad` still has the fit's outward whole-unit snap
 * under it.
 *
 * The other constraint the previous wave tuned against — the root's label
 * versus the horizontal depth-1 chord — is GONE: with the branch-bearing
 * children at 4 and 8 o'clock, the only depth-1 edge any fixture draws
 * (`ma-matrices → ma-eigen`, `sm-dist → sm-testing`) runs from 8 o'clock to 12
 * o'clock and never crosses the root's label band. What survives unchanged is
 * the 12 o'clock child's label clearing the root's dot, which needs
 * `ring > nodeR + labelGap + 5.2 + rootR` — 59.2 here, with 22 units in hand.
 */
export const MOBILE_VIEW: GraphView = withFit({
  w: 360,
  h: 300,
  maxRadius: 163,
  font: 14,
  rootR: 22,
  nodeR: 13,
  labelGap: 19,
  rootLabelAbove: false,
  labelHalo: 3.5,
  edgeW: 1.8,
  fitPad: 2,
});

/** Every view the demo can render in — the sweep target for the bounds test. */
export const GRAPH_VIEWS: GraphView[] = [DESKTOP_VIEW, MOBILE_VIEW];
