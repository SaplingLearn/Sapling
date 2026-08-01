/**
 * Layout + entry-path math for the landing graph demo (#344).
 *
 * Deterministic by construction — no randomness, no time input. The E2E lane
 * parks the animation and asserts against the laid-out frame, so the same graph
 * and viewport must always produce the same coordinates.
 */
import type { CourseGraph } from './courseGraphs';

export interface Point {
  x: number;
  y: number;
}

/**
 * Everything the demo needs to draw itself at one viewport class, in SVG user
 * units. The `<svg>` is `width: 100%`, so the rendered CSS size of *every*
 * dimension below is `value * (renderedWidth / w)` — which is exactly why the
 * desktop numbers can't just be reused on a phone: at a 390px viewport the
 * section's content box is 342px, so the 900-wide desktop viewBox renders at
 * 0.38 scale and a 12-unit label lands at 4.6 CSS px (#344 review #3).
 *
 * The two views are picked apart by `useIsMobile()` in the component. Keeping
 * them as data (rather than a pile of ternaries at each call site) is what lets
 * `layout.test.ts` sweep the entry animation against *both* viewBoxes and prove
 * nothing leaves frame.
 */
export interface GraphView {
  /** viewBox width, user units. */
  w: number;
  /** viewBox height, user units. */
  h: number;
  /** Radius of the outermost ring — the layout's whole spatial budget. */
  maxRadius: number;
  /** Label font-size, user units. */
  font: number;
  /** Root-node circle radius, user units. */
  rootR: number;
  /** Non-root node circle radius, user units. */
  nodeR: number;
  /** Baseline offset of a node's label below the node centre + its radius. */
  labelGap: number;
  /** Edge stroke width, user units. */
  edgeW: number;
}

/**
 * `maxRadius: 232` is byte-identical to what `radialLayout`'s old default
 * (`min(900, 560) / 2 - 48`) produced, so the desktop frame this branch was
 * designed and reviewed against is unchanged.
 */
export const DESKTOP_VIEW: GraphView = {
  w: 900,
  h: 560,
  maxRadius: 232,
  font: 12,
  rootR: 26,
  nodeR: 14,
  labelGap: 16,
  edgeW: 1.4,
};

/**
 * Portrait-ish and much smaller in user units, so a phone's ~342px content box
 * renders it at 0.95 scale instead of 0.38: 13-unit labels land at 12.4 CSS px
 * and non-root dots at a 22.8px diameter (#344 review #3).
 *
 * `maxRadius: 108` is set by the *labels*, not the dots: the outer ring sits on
 * the horizontal axis, so the widest label ("Central Limit", 13 chars) has to
 * clear the right edge — 180 + 108 + (13 × 0.6 × 13) / 2 = 338.7 of 360.
 */
export const MOBILE_VIEW: GraphView = {
  w: 360,
  h: 300,
  maxRadius: 108,
  font: 13,
  rootR: 22,
  nodeR: 12,
  labelGap: 16,
  edgeW: 1.6,
};

/** Every view the demo can render in — the sweep target for the bounds test. */
export const GRAPH_VIEWS: GraphView[] = [DESKTOP_VIEW, MOBILE_VIEW];

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
 * unchanged, but the mobile view passes it explicitly: there the binding
 * constraint is label width against the *narrow* edge, not the inscribed
 * circle, and `min(w, h) / 2 - pad` can't express that.
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
 * the disc of radius |target − centre|, which is bounded by the static layout
 * that `radialLayout` already fits to the viewBox. `layout.test.ts` pins that
 * as an explicit bounds sweep over every fixture × every view.
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
