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
 * Root at the centre, each BFS depth on its own ring, siblings spread evenly
 * around it. Alternate rings are rotated by half a slot so spokes don't line
 * up into visual spokes.
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
    const offset = d % 2 === 0 ? step / 2 : 0;
    ids.forEach((id, i) => {
      const a = i * step + offset - Math.PI / 2;
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
 * On DESKTOP the root's label goes above it (#344 visual 4). Below the root is
 * where the outer-ring → depth-1 edge crosses: in every fixture that edge
 * passes the root's x at `cy + 0.349 × ring` (desktop: 40.5 units down), which
 * is exactly the band a `rootR + labelGap` baseline puts the course code in — a
 * long shallow diagonal straight through "CS 210". Above the root there is only
 * the short vertical spoke to the top child, which the halo breaks cleanly.
 *
 * On MOBILE it stays below, because there the geometry says so. The top child
 * sits `ring` above the root with its own label hanging back down toward it, so
 * an above-the-root label only clears it when
 *
 *     ring ≥ rootR + nodeR + 2·labelGap + cap + descender
 *
 * — 83.8 units at the desktop type scale, against a 116-unit ring: comfortable.
 * The phone's ring is 66 against a 95.7-unit requirement, so "above" would put
 * the course code straight through the first concept's label. The crossing
 * diagonal it would be dodging isn't a problem there anyway: at ring 66 that
 * edge passes the root's x at `cy + 23.0` and the below-baseline label's cap
 * top is at `cy + 34.1`, 11 units clear.
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
 * the way in, so an outer node whose resting place is on the horizontal axis
 * passes through `0.925 × maxRadius` ABOVE and BELOW the centre at ~83% opacity
 * — 215 desktop units against a settled extent of 58. A box fitted to the
 * settled positions clips the assembly in plain view; that exact bug was found
 * and fixed once already on this branch (#344 review #4), and `layout.test.ts`
 * sweeps `t` across the full range to keep it fixed.
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
 * `maxRadius: 232` is byte-identical to what `radialLayout`'s old default
 * (`min(900, 560) / 2 - 48`) produced, so the node positions this branch was
 * designed and reviewed against are unchanged. What changed is the frame drawn
 * around them: the fit resolves to `159 42 578 498` — 578 units wide against
 * the 900 that used to be reserved, i.e. 36% of the box was dead margin.
 *
 * The component caps the rendered width (`md:max-w-[720px]`), so at the cap the
 * graph draws at 1.246 user units per CSS px: 14.9px labels, 34.9px concept
 * dots, a 64.8px root, and a 620px-tall `<svg>` where the old fixed box
 * reserved 737px inside a 1184px container.
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
 * it at 0.84 rather than the 0.57 the desktop frame would give: 14-unit labels
 * land at 11.8 CSS px, concept dots at a 23.6px diameter, and the `<svg>` is
 * 269px tall (#344 review #3).
 *
 * These numbers are RETUNED, not inherited. `maxRadius` used to be pinned at
 * 108 by the *labels* — the outer ring sits on the horizontal axis, so the
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
 * which together need `ring ≥ 2·nodeR + 34.2`. The result clears every pair by
 * 0.8 units instead of overlapping, with 0.8px of label, 3.6px of dot and 8.8px
 * of height in hand against the E2E bars.
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
