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
 * Where a ring's FIRST node sits, as an angle from 3 o'clock. SVG angles run
 * clockwise (y grows downward), so −π/2 is 12 o'clock.
 *
 * THE BUG THIS FIXES. The rule used to be "start at 12 o'clock, and rotate
 * alternate rings by half a slot so spokes don't line up" — `offset = d % 2 ===
 * 0 ? step / 2 : 0` against a `−π/2` start. On a ring of exactly TWO nodes,
 * which is what depth 2 holds in all three fixtures, `step = π`, the half slot
 * is `π/2`, and the two angles collapse to exactly 0 and π: BOTH outer nodes
 * dead on the horizontal axis through the centre. That made the settled layout
 * a flat ellipse (aspect 0.40) sitting inside a near-circular entry sweep
 * (0.86), so the fitted frame could never be tight — the graph filled 45% of
 * its own box height and left a visible dead band above and below it.
 *
 * THE RULE. Every ring starts three quarters of a slot BACK from 3 o'clock, so
 * its angles are `(4i − 3) · step/4` — ODD multiples of `step/4 = π/(2·count)`.
 * An odd multiple of `π/(2n)` is never a multiple of π (that would need
 * `odd = 2kn`), so no ring of ANY size can put a node on the horizontal axis.
 * For the shipped ring sizes it resolves to:
 *
 *   count 3 (depth 1): −3·(2π/3)/4 = −π/2 → 12, 4 and 8 o'clock, i.e. the exact
 *                      triangle this branch was designed and reviewed against.
 *   count 2 (depth 2): −3π/4              → the NW↔SE diagonal.
 *
 * The diagonal's DIRECTION is not free. Every fixture hangs its two outer nodes
 * off the 12 o'clock and 4 o'clock children, so the mirrored diagonal (SW↔NE,
 * `+3·step/4`) drags a depth-1 → depth-2 edge across the centre and straight
 * through a label: −7.2 units of overlap, measured, against +29.2 of clearance
 * the way round it is.
 *
 * `alternate` keeps the half-slot rotation the old rule existed for, but only
 * where it can actually do something: when a ring holds the same number of
 * nodes as the ring inside it, and the two would otherwise line up into radial
 * spokes. Half a slot moves the angles to `(4i − 1) · step/4` — still odd
 * multiples of `step/4`, so the no-horizontal proof holds on that branch too.
 * No shipped fixture reaches it (3 then 2).
 */
function ringPhase(count: number, innerCount: number | undefined): number {
  const step = (Math.PI * 2) / count;
  return (count === innerCount ? -1 : -3) * (step / 4);
}

/**
 * Root at the centre, each BFS depth on its own ring, siblings spread evenly
 * around it, every ring phased by `ringPhase` so none of them flattens onto the
 * horizontal axis.
 *
 * `maxRadius` is the outermost ring's distance from the centre. It defaults to
 * the old inscribed-circle-minus-48 rule so every existing caller and test is
 * unchanged, but each view passes it explicitly: the binding constraint is the
 * *fitted* frame, not the layout box, and `min(w, h) / 2 - pad` can't express
 * that.
 */
export function radialLayout(
  graph: CourseGraph,
  width: number,
  height: number,
  maxRadius: number = Math.min(width, height) / 2 - 48,
): Map<string, Point> {
  const adj = new Map<string, string[]>();
  for (const e of graph.edges) {
    adj.set(e.source, [...(adj.get(e.source) ?? []), e.target]);
    adj.set(e.target, [...(adj.get(e.target) ?? []), e.source]);
  }

  const depth = new Map<string, number>([[graph.rootId, 0]]);
  const queue = [graph.rootId];
  while (queue.length) {
    const cur = queue.shift()!;
    for (const nxt of adj.get(cur) ?? []) {
      if (!depth.has(nxt)) {
        depth.set(nxt, depth.get(cur)! + 1);
        queue.push(nxt);
      }
    }
  }

  const byDepth = new Map<number, string[]>();
  // Iterate graph.nodes (declaration order), not the Map, so ring ordering is
  // stable regardless of BFS visit order.
  for (const n of graph.nodes) {
    const d = depth.get(n.id) ?? 0;
    byDepth.set(d, [...(byDepth.get(d) ?? []), n.id]);
  }

  const cx = width / 2;
  const cy = height / 2;
  const maxDepth = Math.max(...byDepth.keys(), 1);
  const ring = maxRadius / maxDepth;

  const out = new Map<string, Point>();
  for (const [d, ids] of byDepth) {
    if (d === 0) {
      for (const id of ids) out.set(id, { x: cx, y: cy });
      continue;
    }
    const step = (Math.PI * 2) / ids.length;
    // Depth 0 is the centre, not a ring, so the innermost ring has nothing to
    // line up with and never alternates.
    const phase = ringPhase(ids.length, d > 1 ? byDepth.get(d - 1)?.length : undefined);
    ids.forEach((id, i) => {
      const a = i * step + phase;
      out.set(id, {
        x: cx + Math.cos(a) * ring * d,
        y: cy + Math.sin(a) * ring * d,
      });
    });
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
 * On DESKTOP the root's label goes above it (#344 visual 4). It went there to
 * dodge the outer-ring → depth-1 edge, which the old flat ring dragged across
 * the root's x at `cy + 0.349 × ring` — straight through "CS 210". The ring
 * phase (see `ringPhase`) has since pulled that diagonal off the centre, so
 * below is no longer a collision either; above is kept because it is still the
 * roomier half. Measured, across all three fixtures: above clears everything by
 * 29.2 units, below by 11.5 — the binding neighbour there is the depth-1 chord
 * (`ma-matrices → ma-eigen`, `sm-dist → sm-testing`) at `cy + ring/2`, i.e.
 * `cy + 58`, against a below-baseline label bottom at `cy + 46.5`.
 *
 * On MOBILE it stays below, because there the geometry says so. The top child
 * sits `ring` above the root with its own label hanging back down toward it, so
 * an above-the-root label only clears it when
 *
 *     ring ≥ rootR + nodeR + 2·labelGap + cap + descender
 *
 * — 83.8 units at the desktop type scale, against a 116-unit ring: comfortable.
 * The phone's ring is 66 against a 95.7-unit requirement, so "above" would put
 * the course code straight through the first concept's label. Below is tight
 * but positive: the same depth-1 chord passes at `cy + 33.0` and the
 * below-baseline label's cap top is at `cy + 34.1`, 1.1 units clear — which is
 * the constraint `MOBILE_VIEW`'s geometry was tuned against, and it does not
 * move with the ring phase.
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
 * rest: on desktop the sweep reaches ~237 units above and below the centre
 * while the settled drawing only reaches 178 above and 199 below. A box fitted
 * to the settled positions would clip 59 units — 81 CSS px at the rendered cap
 * — off the top and bottom of the assembly, in plain view; that exact bug was
 * found and fixed once already on this branch (#344 review #4). `layout.test.ts`
 * sweeps `t` across the full range to keep it fixed, and pins the overshoot
 * itself so a settled-fit implementation fails outright.
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
 * `maxRadius: 232` is still `radialLayout`'s old default (`min(900, 560) / 2 -
 * 48`), so the layout's spatial budget is unchanged and the depth-1 ring sits
 * exactly where this branch was designed against. What moved is the outer ring
 * — `ringPhase` takes it off the horizontal axis and onto the diagonal — and
 * the frame fitted around the result: `185 33 526 516`, against the
 * `0 0 900 560` the demo shipped with and the `159 42 578 498` the flat ring
 * fitted to.
 *
 * The component caps the rendered width (`md:max-w-[720px]`), so at the cap the
 * graph draws at 1.369 user units per CSS px: 16.4px labels, 38.3px concept
 * dots, a 71px root, and a 706px-tall `<svg>` where the fixed box reserved
 * 737px inside a 1184px container. The settled drawing fills 73% of that height
 * (515 of 706 CSS px); on the flat ring it filled 45% (277 of 620), which is
 * the dead band above and below the graph that this phase change removes.
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
 * Portrait-ish and much smaller in user units, so a phone's ~332px content box
 * (390 viewport − 48 of `px-6` − the 10px scrollbar globals.css paints) renders
 * it at 0.91 rather than the 0.63 the desktop frame would give: 14-unit labels
 * land at 12.8 CSS px, concept dots at a 25.5px diameter, and the `<svg>` is
 * 301px tall (#344 review #3). The frame is `-4 -1 364 330`; the diagonal outer
 * ring both narrowed it (394 → 364) and filled it — the settled drawing is 73%
 * of its height, up from 48%.
 *
 * These numbers are RETUNED, not inherited. `maxRadius` used to be pinned at
 * 108 by the *labels* — the outer ring then sat on the horizontal axis, so the
 * widest one ("Central Limit") had to clear the hardcoded 360-unit edge. The
 * fitted frame absorbs that overhang now, and it also removes ~26 units of dead
 * width, which shrinks the rendered height: keeping the old geometry under the
 * fit lands the phone `<svg>` at 259px and fails the E2E legibility gate
 * (≥11px labels, ≥20px dots, >260px tall) outright.
 *
 * So the phone geometry was searched against that gate AND against the settled
 * frame's crowding, which the old numbers were already losing (they overlapped
 * by 1.5 units before the halo, 3.2 with it). Two constraints bracket the ring
 * from both sides and are what picked 132/14/14/22:
 *
 *   root label vs the horizontal depth-1 edge:  rootR + labelGap ≥ ring/2 + 11.9
 *   top child's label vs the root's own dot:    rootR + labelGap ≤ ring − nodeR − 5.2
 *
 * which together need `ring ≥ 2·nodeR + 34.2`. Neither constraint moves with
 * the ring phase — both are about the root, its own top child, and the depth-1
 * chord — so the retune survives it unchanged: still +0.8 units on the worst
 * pair, now with 1.8px of label, 5.5px of dot and 41px of height in hand
 * against the E2E bars (the tighter frame renders everything larger).
 */
export const MOBILE_VIEW: GraphView = withFit({
  w: 360,
  h: 300,
  maxRadius: 132,
  font: 14,
  rootR: 24,
  nodeR: 14,
  labelGap: 22,
  rootLabelAbove: false,
  labelHalo: 3.4,
  edgeW: 1.8,
  fitPad: 10,
});

/** Every view the demo can render in — the sweep target for the bounds test. */
export const GRAPH_VIEWS: GraphView[] = [DESKTOP_VIEW, MOBILE_VIEW];
