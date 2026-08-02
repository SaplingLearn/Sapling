/**
 * The layout is deterministic on purpose: the E2E lane parks the animation and
 * asserts against a laid-out frame, so identical input must give identical
 * coordinates on every run and in every environment.
 */
import { describe, it, expect } from 'vitest';

import { COURSE_GRAPHS, type CourseGraph } from './courseGraphs';
import {
  DESKTOP_VIEW,
  GRAPH_VIEWS,
  MOBILE_VIEW,
  easeOutCubic,
  fitViewBox,
  helixEntry,
  labelBaselineY,
  radialLayout,
  viewBoxAttr,
} from './layout';

const G = COURSE_GRAPHS[0];

/**
 * The BFS spanning tree of the undirected graph — restated here rather than
 * exported from `layout.ts`, so the assertions below are an INDEPENDENT reading
 * of the same fixtures. (Deliberately not `DemoNode.children`: that field is
 * dead data that disagrees with `edges`, which is exactly why the layout must
 * not read it either.)
 */
function bfsTree(graph: CourseGraph) {
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

const dist = (a: { x: number; y: number }, b: { x: number; y: number }) =>
  Math.hypot(a.x - b.x, a.y - b.y);

describe('radialLayout', () => {
  it('positions every node', () => {
    const p = radialLayout(G, 800, 500);
    expect(p.size).toBe(G.nodes.length);
    for (const n of G.nodes) expect(p.get(n.id)).toBeDefined();
  });

  /**
   * CRITERION 1 — the whole point of this wave. The section is called "Pick a
   * course. Watch it grow." and the product is called Sapling; the layout used
   * to spread depth-1 around the FULL circle with the root at the frame's
   * centre, so the drawing grew one arm up and two down and read as an inverted
   * Y. Every node that is not the root now sits STRICTLY ABOVE it — smaller y,
   * SVG coordinates — in every fixture, in every shipped view.
   *
   * Asserted as a margin rather than as `< rootY` so a layout that merely
   * grazes the root's own line (the ring layout put two nodes exactly on it)
   * cannot squeak through: the closest any node comes is `ring · sin(π/4)`,
   * measured 113.1 units on desktop and 74.9 on the phone.
   */
  it('grows upward — every node sits strictly above the root', () => {
    for (const graph of COURSE_GRAPHS) {
      for (const view of GRAPH_VIEWS) {
        const pts = radialLayout(graph, view.w, view.h, view.maxRadius);
        const root = pts.get(graph.rootId)!;
        for (const n of graph.nodes) {
          if (n.id === graph.rootId) continue;
          expect(
            pts.get(n.id)!.y,
            `${graph.id}/${n.id} at maxRadius ${view.maxRadius}`,
          ).toBeLessThan(root.y - view.nodeR);
        }
      }
    }
  });

  /**
   * …and the other half of criterion 1: the root is at the BOTTOM-CENTRE of the
   * content, not in the middle of it.
   *
   * `radialLayout` lays the skeleton out with the root at the origin and then
   * translates it as a rigid body until the skeleton's own bounding box is
   * centred on `(w/2, h/2)` — the point `helixEntry` spirals around and
   * `fitViewBox` fits its frame about. So the root is the LOWEST node, it is
   * horizontally centred in the drawing (the fan is mirror-symmetric), and it
   * sits BELOW the layout centre rather than on it.
   */
  it('puts the root at the bottom-centre of the content', () => {
    const p = radialLayout(G, 800, 500);
    const root = p.get(G.rootId)!;
    const xs = [...p.values()].map((q) => q.x);
    const ys = [...p.values()].map((q) => q.y);

    expect(root.y).toBe(Math.max(...ys));
    expect(root.x).toBeCloseTo((Math.min(...xs) + Math.max(...xs)) / 2, 6);
    expect(root.x).toBeCloseTo(400, 6);
    expect(root.y).toBeGreaterThan(250);
    // The skeleton, not the root, is what is centred on the layout box.
    expect((Math.min(...ys) + Math.max(...ys)) / 2).toBeCloseTo(250, 6);
  });

  it('is deterministic', () => {
    expect(radialLayout(G, 800, 500)).toEqual(radialLayout(G, 800, 500));
  });

  it('separates nodes at the same depth', () => {
    const p = radialLayout(G, 800, 500);
    const depth1 = G.nodes.find((n) => n.id === G.rootId)!.children;
    const pts = depth1.map((id) => p.get(id)!);
    for (let i = 0; i < pts.length; i++) {
      for (let j = i + 1; j < pts.length; j++) {
        const d = Math.hypot(pts[i].x - pts[j].x, pts[i].y - pts[j].y);
        expect(d).toBeGreaterThan(40);
      }
    }
  });

  it('scales with the viewport', () => {
    const small = radialLayout(G, 400, 300);
    const large = radialLayout(G, 1200, 800);
    expect(small).not.toEqual(large);
  });

  /**
   * CRITERION 1, and the pin the whole rewrite hangs on.
   *
   * The layout used to be global concentric rings: a node's angle came from its
   * index within its depth, with no relationship to where its parent sat. This
   * is the invariant that says otherwise — a child is placed off ITS OWN
   * PARENT, so the distance between the two is exactly one ring step, for every
   * non-root node, in every fixture, in every view.
   *
   * It fails outright on the ring layout, where the same edges measured 116.0
   * AND 170.9 units on desktop depending on which ring angles happened to line
   * up (`cs-arrays → cs-sorting` was the 170.9).
   */
  it('places every node exactly one ring step from its BFS parent', () => {
    for (const graph of COURSE_GRAPHS) {
      for (const view of GRAPH_VIEWS) {
        const pts = radialLayout(graph, view.w, view.h, view.maxRadius);
        const { depth, parent } = bfsTree(graph);
        // maxDepth is 2 in every fixture, so the step is half the budget.
        const step = view.maxRadius / Math.max(...depth.values());
        for (const n of graph.nodes) {
          if (n.id === graph.rootId) continue;
          const d = dist(pts.get(n.id)!, pts.get(parent.get(n.id)!)!);
          expect(d, `${graph.id}/${n.id} → ${parent.get(n.id)}`).toBeCloseTo(step, 6);
        }
      }
    }
  });

  /**
   * CRITERION 1 as the brief states it: a child sits WITH its parent, i.e. its
   * BFS parent is the nearest node of the previous depth. Weaker than the
   * one-ring-step pin above (the ring layout happens to satisfy it too), but it
   * is the property a reader actually cares about, so it is asserted rather
   * than implied — and it stays true for a parent with several children, where
   * the exact-step assertion alone would not rule out a child drifting nearer
   * to somebody else's parent.
   */
  it('keeps every node nearer its own parent than any other node of that depth', () => {
    for (const graph of COURSE_GRAPHS) {
      for (const view of GRAPH_VIEWS) {
        const pts = radialLayout(graph, view.w, view.h, view.maxRadius);
        const { depth, parent } = bfsTree(graph);
        for (const n of graph.nodes) {
          if (n.id === graph.rootId) continue;
          const mine = dist(pts.get(n.id)!, pts.get(parent.get(n.id)!)!);
          for (const other of graph.nodes) {
            if (other.id === parent.get(n.id)) continue;
            if (depth.get(other.id) !== depth.get(n.id)! - 1) continue;
            expect(
              dist(pts.get(n.id)!, pts.get(other.id)!),
              `${graph.id}/${n.id}: ${other.id} is nearer than its parent ${parent.get(n.id)}`,
            ).toBeGreaterThan(mine);
          }
        }
      }
    }
  });

  /**
   * CRITERION 2 — no long flung edges. Measured over the TREE edges, which are
   * the ones the layout is responsible for; cross-edges are drawn but not
   * positioned (see below).
   *
   * Desktop, before → after: max 170.9 → 116.0, mean 128.5 → 116.0. Phone:
   * max 97.3 → 81.5, mean 73.1 → 81.5 (the phone's ring grew with the retune,
   * so its mean rises while its max falls). Asserted against the ring step
   * rather than a magic number, so it stays meaningful if a view is retuned.
   */
  it('draws no tree edge longer than one ring step', () => {
    for (const graph of COURSE_GRAPHS) {
      for (const view of GRAPH_VIEWS) {
        const pts = radialLayout(graph, view.w, view.h, view.maxRadius);
        const { depth, parent } = bfsTree(graph);
        const step = view.maxRadius / Math.max(...depth.values());
        const lengths = graph.edges
          .filter((e) => parent.get(e.target) === e.source || parent.get(e.source) === e.target)
          .map((e) => dist(pts.get(e.source)!, pts.get(e.target)!));
        expect(lengths.length, `${graph.id} tree edges`).toBe(graph.nodes.length - 1);
        expect(Math.max(...lengths), `${graph.id} longest tree edge`).toBeLessThanOrEqual(
          step + 1e-9,
        );
      }
    }
  });

  /**
   * The tree governs POSITION only. Every fixture carries exactly one edge that
   * is NOT a tree edge — `cs-sorting → cs-complexity`, `ma-matrices →
   * ma-eigen`, `sm-dist → sm-testing` — and `AssemblingGraph` maps
   * `graph.edges`, so all of them are still drawn; cs210's closes a triangle
   * from the lower-right tip back up to the top node and is a good part of why
   * the picture reads as a graph rather than a star. Pinned here because a
   * future "just draw the tree" simplification would silently drop it.
   */
  it('leaves the fixtures with a drawn cross-edge the tree does not own', () => {
    for (const graph of COURSE_GRAPHS) {
      const { parent } = bfsTree(graph);
      const cross = graph.edges.filter(
        (e) => parent.get(e.target) !== e.source && parent.get(e.source) !== e.target,
      );
      expect(cross.length, `${graph.id} cross-edges`).toBe(1);
      // …and both of its endpoints are laid out, so it is drawable.
      const pts = radialLayout(graph, DESKTOP_VIEW.w, DESKTOP_VIEW.h, DESKTOP_VIEW.maxRadius);
      expect(pts.get(cross[0].source)).toBeDefined();
      expect(pts.get(cross[0].target)).toBeDefined();
    }
  });

  /**
   * The no-horizontal invariant, carried over — RETARGETED AT THE ROOT, which
   * is the only retarget in this file that changes what is measured rather than
   * what the number is.
   *
   * It used to measure the angle from `(w/2, h/2)`, which was the root. It is
   * not any more: the root sits at the bottom-centre of the content and
   * `(w/2, h/2)` is the centre of the skeleton's bounding box — the point the
   * entry sweep spirals around. The line that matters for the drawing has
   * always been "the horizontal through the node everything radiates from", and
   * that node is the root. Measured off `(w/2, h/2)` instead, the two outer
   * depth-1 children now sit exactly ON it by construction (the fan's tips and
   * the root define the box, so its mid-line runs through them) — which is
   * geometrically meaningless and would fail a test whose subject no longer
   * exists.
   *
   * Off the ROOT the invariant is stronger than it has ever been: the closest
   * any node comes to the horizon is `sin(π/4)` = 0.707, against 0.5 for the
   * downward tree and exactly 0 for the ring layout it replaced. The bar stays
   * at the 0.4 the previous wave set.
   */
  it('never lands a node on the horizontal axis through the root', () => {
    for (const graph of COURSE_GRAPHS) {
      for (const view of GRAPH_VIEWS) {
        const pts = radialLayout(graph, view.w, view.h, view.maxRadius);
        const root = pts.get(graph.rootId)!;
        for (const n of graph.nodes) {
          if (n.id === graph.rootId) continue;
          const p = pts.get(n.id)!;
          const dx = p.x - root.x;
          const dy = p.y - root.y;
          expect(
            Math.abs(dy) / Math.hypot(dx, dy),
            `${graph.id}/${n.id} at maxRadius ${view.maxRadius}`,
          ).toBeGreaterThan(0.4);
        }
      }
    }
  });

  /**
   * …and the invariant `fanAngle` actually claims, which is stronger than the
   * three fixtures: for a fan of ANY size the seat angles are
   * `−π + k·π/(count+1)` for `k` in `1…count`, so the closest one can ever come
   * to the horizontal is `sin(π/(count+1))`. Swept over fan sizes 1…24 on
   * synthetic star graphs, with the count-aware floor rather than a flat
   * number, because a flat number is only meaningful for the fan sizes that
   * happen to ship today.
   *
   * The floor is the one the previous wave's `ringPhase` guaranteed —
   * `sin(π/(2·count))` — kept deliberately: `π/(count+1) ≥ π/(2·count)` for
   * every `count ≥ 1`, so passing it proves the new rule is never worse than
   * the old one at any size, not merely that it happens to pass its own bar.
   */
  it('holds the no-horizontal invariant at any fan size', () => {
    const star = (count: number): CourseGraph => ({
      id: `star${count}`,
      code: 'X',
      name: 'X',
      rootId: 'r',
      nodes: [
        { id: 'r', label: 'r', tier: 'learning', blurb: '', children: [] },
        ...Array.from({ length: count }, (_, i) => ({
          id: `n${i}`,
          label: `n${i}`,
          tier: 'learning' as const,
          blurb: '',
          children: [],
        })),
      ],
      edges: Array.from({ length: count }, (_, i) => ({ source: 'r', target: `n${i}` })),
    });

    for (let count = 1; count <= 24; count++) {
      const pts = radialLayout(star(count), 900, 560, 232);
      const root = pts.get('r')!;
      // The bar the previous wave's ring phase guaranteed, minus float slop.
      const floor = Math.sin(Math.PI / (2 * count)) * 0.999;
      for (let i = 0; i < count; i++) {
        const p = pts.get(`n${i}`)!;
        const sin = Math.abs(p.y - root.y) / Math.hypot(p.x - root.x, p.y - root.y);
        expect(sin, `fan of ${count}, node ${i}`).toBeGreaterThan(floor);
        // …and every one of them is above the root, at any fan size.
        expect(p.y, `fan of ${count}, node ${i}`).toBeLessThan(root.y);
      }
    }
  });

  /**
   * The wedge rule, which no shipped fixture exercises — every parent below the
   * root has exactly one child, so every arm is collinear with its parent. This
   * pins what happens when one doesn't: siblings SHARE their parent's angular
   * span, evenly and symmetrically about the direction that parent itself grew
   * in, so a branchy graph fans out instead of stacking on one ray.
   *
   * RETARGETED, not weakened. Two of its numbers moved with the angular domain,
   * and both moves are the subject of this wave:
   *
   * - the axis. It used to be measured as the bearing from `(w/2, h/2)` to the
   *   parent, which was the same thing as "the direction the parent grew" only
   *   because the root sat at `(w/2, h/2)`. It no longer does, so the axis is
   *   now read off the root — which is what "the parent's outward direction"
   *   meant all along.
   * - the span. Depth-1 used to own a full `2π/count` slot of a circle; it now
   *   owns a `π/(count+1)` slot of the upward half-plane. With two children
   *   that is π/3 rather than π, so three grandchildren land at −π/9, 0, +π/9
   *   off the axis instead of −π/3, 0, +π/3. The RULE — even, symmetric
   *   subdivision of exactly the parent's own span — is unchanged and is what
   *   is asserted; the arithmetic is derived from `π/(count+1)` in the test so
   *   it cannot drift from the implementation silently.
   */
  it('splits a parent’s wedge evenly between its children', () => {
    const graph: CourseGraph = {
      id: 'fan',
      code: 'X',
      name: 'X',
      rootId: 'r',
      nodes: ['r', 'a', 'b', 'a1', 'a2', 'a3'].map((id) => ({
        id,
        label: id,
        tier: 'learning' as const,
        blurb: '',
        children: [],
      })),
      edges: [
        { source: 'r', target: 'a' },
        { source: 'r', target: 'b' },
        { source: 'a', target: 'a1' },
        { source: 'a', target: 'a2' },
        { source: 'a', target: 'a3' },
      ],
    };
    const pts = radialLayout(graph, 900, 560, 232);
    const a = pts.get('a')!;
    const root = pts.get('r')!;
    // Direction from `a` to each child, measured off `a`. The wedge's own axis
    // is the direction `a` itself grew in, i.e. the bearing from the ROOT.
    const bearing = (id: string) => Math.atan2(pts.get(id)!.y - a.y, pts.get(id)!.x - a.x);
    const outward = Math.atan2(a.y - root.y, a.x - root.x);
    // `a` and `b` take two of a 3-way split of the upward half-plane, so `a`
    // owns a π/3 wedge; three children take the centres of three π/9 slices.
    const slice = Math.PI / (2 + 1) / 3;
    expect(bearing('a1') - outward).toBeCloseTo(-slice, 6);
    expect(bearing('a2') - outward).toBeCloseTo(0, 6);
    expect(bearing('a3') - outward).toBeCloseTo(slice, 6);
    // Symmetric about the axis, and all still one ring step out.
    for (const id of ['a1', 'a2', 'a3']) {
      expect(Math.hypot(pts.get(id)!.x - a.x, pts.get(id)!.y - a.y), id).toBeCloseTo(116, 6);
    }
    // A child pushed off its parent's outward direction lands INSIDE maxRadius
    // of the root — `maxRadius` is a budget, not an outer ring.
    for (const id of ['a1', 'a3']) {
      expect(Math.hypot(pts.get(id)!.x - root.x, pts.get(id)!.y - root.y), id).toBeLessThan(232);
    }
    // The deeper subtree took an OUTER seat: `a` carries three children and `b`
    // none, so `a` is further from the vertical through the root than `b` is.
    const off = (id: string) => Math.abs(pts.get(id)!.x - root.x);
    expect(off('a')).toBeGreaterThan(off('b') - 1e-9);
  });

  it('keeps the default maxRadius at the old inscribed-circle rule', () => {
    // The `maxRadius` parameter was added for the mobile view (#344 review #3).
    // Its DEFAULT is unchanged, so every caller that omits it — the two tests
    // above, and anything outside this module — keeps the geometry it had.
    expect(radialLayout(G, 900, 560)).toEqual(
      radialLayout(G, 900, 560, Math.min(900, 560) / 2 - 48),
    );
    // DESKTOP_VIEW no longer takes that default (232 → 320), and the assertion
    // that it did is gone rather than adjusted, because the identity was never
    // the point: the layout box only fixes the entry sweep's centre, while the
    // spatial budget is bracketed by the rendered type scale, the label
    // clearances and the phone's legibility floor. Pinning the value is this
    // test's job; pinning it to an arithmetic coincidence with `w`/`h` would
    // just re-break the moment either is retuned.
    expect(DESKTOP_VIEW.maxRadius).toBe(320);
    expect(MOBILE_VIEW.maxRadius).toBe(212);
  });
});

describe('easeOutCubic', () => {
  it('pins its endpoints and clamps', () => {
    expect(easeOutCubic(0)).toBe(0);
    expect(easeOutCubic(1)).toBe(1);
    expect(easeOutCubic(-1)).toBe(0);
    expect(easeOutCubic(4)).toBe(1);
  });
});

describe('helixEntry', () => {
  const target = { x: 300, y: 120 };
  const centre = { x: 200, y: 200 };

  it('lands exactly on the target at t=1', () => {
    const r = helixEntry(target, centre, 1);
    expect(r.x).toBeCloseTo(target.x, 6);
    expect(r.y).toBeCloseTo(target.y, 6);
    expect(r.scale).toBeCloseTo(1, 6);
    expect(r.opacity).toBeCloseTo(1, 6);
  });

  it('starts invisible and small', () => {
    const r = helixEntry(target, centre, 0);
    expect(r.opacity).toBe(0);
    expect(r.scale).toBeLessThan(0.5);
  });

  /**
   * THE ENTRY IS A HELIX, NOT A FADE-IN — and this is the test that has to keep
   * meaning that now the sweep is a quarter turn instead of 1.5 turns.
   *
   * Both bars are stated as SHAPE, not as a distance in units, because a
   * distance bar silently weakens whenever the travel radius or the geometry
   * moves. The measurements are taken at mid-flight (t = 0.5), where
   * `easeOutCubic` has 12.5% of the entry left to run:
   *
   * - the node is more than a TENTH OF ITS OWN TRAVEL RADIUS off the point a
   *   straight-line entry with the same easing would be at (measured 0.172, i.e.
   *   21.97 units on this 128.06-unit example — it was 129.61 units at 1.5
   *   turns, but 1.01 radii, because at 540° the "straight line" comparison is
   *   meaningless: the node is halfway round the far side);
   * - and it is more than 5° off its own settled BEARING from the centre
   *   (measured 11.25° = 12.5% of the quarter turn), which is the part a plain
   *   scale-and-fade cannot fake at any distance.
   *
   * The old bar was `> 10` units, i.e. 7.8% of this radius, so the floor went
   * UP with the sweep coming down. `ENTRY_CONTRACTION = 1` is what makes the
   * first number readable: the radial term is then exactly the straight line's
   * own easing, so every unit of deviation measured here is rotation.
   *
   * Both bars BITE. Mid-flight offset is `2·e·sin(45°·turns)` radii and the
   * swing is `45°·turns`, so dropping the entry to 0.146 turns fails the first
   * and 0.111 fails the second — i.e. this test is what stops the next person
   * from tightening the frame the lazy way, by taking the helix out entirely.
   */
  it('rotates around the centre on the way in — the helix', () => {
    const mid = helixEntry(target, centre, 0.5);
    const straight = {
      x: centre.x + (target.x - centre.x) * easeOutCubic(0.5),
      y: centre.y + (target.y - centre.y) * easeOutCubic(0.5),
    };
    const travel = Math.hypot(target.x - centre.x, target.y - centre.y);
    const off = Math.hypot(mid.x - straight.x, mid.y - straight.y);
    expect(off / travel, 'mid-flight offset from the straight line, in radii').toBeGreaterThan(0.1);

    const bearing = (p: { x: number; y: number }) =>
      Math.atan2(p.y - centre.y, p.x - centre.x);
    const swing = Math.abs(bearing(mid) - bearing(target)) * (180 / Math.PI);
    expect(swing, 'mid-flight bearing swing, degrees').toBeGreaterThan(5);
  });

  it('grows monotonically', () => {
    let prev = -1;
    for (let t = 0; t <= 1.0001; t += 0.1) {
      const s = helixEntry(target, centre, t).scale;
      expect(s).toBeGreaterThan(prev);
      prev = s;
    }
  });

  it('never travels further from the centre than its own target does', () => {
    // The invariant behind the bounds sweep below: the entry path only ever
    // *contracts* toward the centre, so the whole sweep lives inside the disc
    // the static layout already fits to the viewBox. The pre-fix version
    // stretched to 1.9× at t=0 and this fails outright (#344 review #4).
    const targetRadius = Math.hypot(target.x - centre.x, target.y - centre.y);
    for (let i = 0; i <= 1000; i++) {
      const h = helixEntry(target, centre, i / 1000);
      expect(Math.hypot(h.x - centre.x, h.y - centre.y)).toBeLessThanOrEqual(targetRadius + 1e-9);
    }
  });
});

/**
 * Labels render in JetBrains Mono, whose advance width is 600/1000 em. The text
 * is `textAnchor="middle"`, so half the string hangs off each side of the
 * node's x. Restated here rather than imported from `layout.ts` so the sweep
 * below stays an independent measurement of the frame the fit produced.
 */
const MONO_ADVANCE_EM = 0.6;

/** Everything a node draws at one instant: its dot, and its label box. */
function drawnExtent(
  view: (typeof GRAPH_VIEWS)[number],
  label: string,
  isRoot: boolean,
  x: number,
  y: number,
  r: number,
  scale: number,
) {
  const dotR = r * scale;
  const half = (label.length * MONO_ADVANCE_EM * view.font) / 2 + view.labelHalo / 2;
  const baseline = labelBaselineY(view, isRoot, y, r);
  return {
    left: Math.min(x - dotR, x - half),
    right: Math.max(x + dotR, x + half),
    // 0.73em of cap height above the baseline, 0.25em of descender below it.
    top: Math.min(y - dotR, baseline - view.font * 0.73 - view.labelHalo / 2),
    bottom: Math.max(y + dotR, baseline + view.font * 0.25 + view.labelHalo / 2),
  };
}

/**
 * The height of the SETTLED drawing — top of the highest ink to bottom of the
 * lowest, across every fixture, in user units. Not the frame: the frame also
 * holds the entry sweep's headroom, and telling the two apart is the whole
 * subject of the phone-sizing test below that uses it.
 */
function settledHeight(view: (typeof GRAPH_VIEWS)[number]): number {
  let top = Infinity;
  let bottom = -Infinity;
  for (const graph of COURSE_GRAPHS) {
    const points = radialLayout(graph, view.w, view.h, view.maxRadius);
    for (const n of graph.nodes) {
      const p = points.get(n.id)!;
      const isRoot = n.id === graph.rootId;
      const e = drawnExtent(view, n.label, isRoot, p.x, p.y, isRoot ? view.rootR : view.nodeR, 1);
      top = Math.min(top, e.top);
      bottom = Math.max(bottom, e.bottom);
    }
  }
  return bottom - top;
}

/**
 * #344 review #4 — the bug this file should have caught during development.
 *
 * The entry path used to stretch the offset from the centre by up to 1.9×, so
 * against the real desktop layout the outer ring swung to y = 693 (133px past
 * the 560-unit viewBox edge), got chopped by the `<svg>` viewport, and crossed
 * back in at opacity ≈ 0.5 — plainly visible, and invisible in review only
 * because the animation was also playing off-screen (review #1).
 *
 * Retargeted at the DERIVED frame (#344 visual 3): the viewBox is no longer a
 * hardcoded `0 0 900 560` with room to spare, it is fitted to this very sweep,
 * so "does the frame still contain the assembly" is now a question about the
 * fit — and a too-small pad, a stale fit, or a hand-written viewBox all land
 * here.
 *
 * So: sweep `t` across the whole entry for every node of every fixture in every
 * view, and assert that the drawn extent — circle, label, halo — never leaves
 * the fitted box.
 */
describe('helixEntry × radialLayout — nothing leaves the fitted viewBox', () => {
  const STEPS = 400;

  for (const view of GRAPH_VIEWS) {
    for (const graph of COURSE_GRAPHS) {
      it(`${graph.id} stays inside ${viewBoxAttr(view.fit)} across the whole sweep`, () => {
        const points = radialLayout(graph, view.w, view.h, view.maxRadius);
        const centre = { x: view.w / 2, y: view.h / 2 };
        const { x, y, w, h } = view.fit;

        for (const n of graph.nodes) {
          const p = points.get(n.id)!;
          const isRoot = n.id === graph.rootId;
          const r = isRoot ? view.rootR : view.nodeR;

          for (let i = 0; i <= STEPS; i++) {
            const t = i / STEPS;
            const f = helixEntry(p, centre, t);
            const e = drawnExtent(view, n.label, isRoot, f.x, f.y, r, f.scale);
            const where = `${graph.id}/${n.id} @ t=${t.toFixed(3)}`;

            expect(e.left, `${where} left`).toBeGreaterThanOrEqual(x);
            expect(e.right, `${where} right`).toBeLessThanOrEqual(x + w);
            expect(e.top, `${where} top`).toBeGreaterThanOrEqual(y);
            expect(e.bottom, `${where} bottom`).toBeLessThanOrEqual(y + h);
          }
        }
      });
    }
  }

  /**
   * The assertion above is only worth anything if the sweep actually needs the
   * headroom — otherwise a lazy "fit to the settled node positions" would pass
   * it, and that is precisely the clipping bug (#344 review #4). So: build the
   * box a settled fit would produce, and prove the ASSEMBLY LEAVES IT.
   *
   * That is now asserted directly rather than through the old proxy. The proxy
   * was "the swept box overhangs the settled box by more than 25 units on the
   * top AND the bottom", which held while `helixEntry` turned 1.5 times and
   * every node passed through every direction (desktop 125.8 / 103.6 units,
   * mobile 82.9 / 69.6). At the quarter turn it does not, and the reason is
   * geometry rather than a weaker guard:
   *
   * - the fan's tips sit far from the centre and only ~27° above the horizontal,
   *   so rotating them toward the vertical lifts them PAST the settled top —
   *   desktop by 27.9 units (34.5 CSS px at the cap), mobile by 17.6 (13.6 px),
   *   both at ~80% opacity, both plainly visible if the frame did not hold them;
   * - nothing can swing BELOW the settled bottom, because the lowest ink is the
   *   course code hanging under the root and the root is the node nearest the
   *   centre. The bottom overhang is exactly 0, and the frame's bottom edge is
   *   the settled bottom plus `fitPad` by construction.
   *
   * So the top overhang is asserted with a number, the bottom is asserted to be
   * non-negative (the sweep never dips below the frame's floor), and the
   * settled-fit box is built and shown to clip — which is the property the whole
   * `fitViewBox` doc comment is about, and which no amount of retuning can make
   * vacuous.
   */
  for (const view of GRAPH_VIEWS) {
    it(`the ${view.maxRadius}-radius sweep leaves the settled bounding box`, () => {
      const centre = { x: view.w / 2, y: view.h / 2 };
      let settledTop = Infinity;
      let settledBottom = -Infinity;
      let sweptTop = Infinity;
      let sweptBottom = -Infinity;

      for (const graph of COURSE_GRAPHS) {
        const points = radialLayout(graph, view.w, view.h, view.maxRadius);
        for (const n of graph.nodes) {
          const p = points.get(n.id)!;
          const isRoot = n.id === graph.rootId;
          const r = isRoot ? view.rootR : view.nodeR;

          const rest = drawnExtent(view, n.label, isRoot, p.x, p.y, r, 1);
          settledTop = Math.min(settledTop, rest.top);
          settledBottom = Math.max(settledBottom, rest.bottom);

          for (let i = 0; i <= 400; i++) {
            const f = helixEntry(p, centre, i / 400);
            const e = drawnExtent(view, n.label, isRoot, f.x, f.y, r, f.scale);
            sweptTop = Math.min(sweptTop, e.top);
            sweptBottom = Math.max(sweptBottom, e.bottom);
          }
        }
      }

      // The assembly rises this far above where it comes to rest — desktop
      // 27.9 units, mobile 17.6 — and a frame fitted to the rest state would
      // chop exactly that much off the top of it, live, at ~80% opacity.
      expect(settledTop - sweptTop, 'sweep above the settled top').toBeGreaterThan(12);
      // Nothing ever swings below the course code: the frame's floor is the
      // settled floor, and the sweep must not need more than that.
      expect(sweptBottom - settledBottom, 'sweep below the settled bottom').toBeGreaterThanOrEqual(
        0,
      );
      // …and the fitted frame is sized for the sweep, not for the rest state.
      expect(view.fit.h).toBeGreaterThanOrEqual(sweptBottom - sweptTop);
      expect(view.fit.h).toBeGreaterThan(settledBottom - settledTop);

      // The bug, stated as the bug: fit the frame to the settled positions the
      // way the demo originally did, and the assembly leaves it.
      const settledFit = {
        top: Math.floor(settledTop - view.fitPad),
        bottom: Math.ceil(settledBottom + view.fitPad),
      };
      expect(
        settledFit.top - sweptTop,
        'how far the assembly escapes a settled-fitted frame',
      ).toBeGreaterThan(10);
    });
  }

  /**
   * CRITERION 4/5 — the settled drawing has to be a SANE SHAPE, sitting in the
   * middle of the frame it is given.
   *
   * TWO BARS MOVED WITH THE UPWARD FAN, both downward; the tightened entry
   * sweep has now put one of them back, well above where it started.
   *
   * The ASPECT WINDOW goes 0.55–1.10 → 0.40–0.80. A canopy is legitimately
   * wider than tall: three shoots leaving one base 45° apart, two of them
   * carrying a second segment, make an object about twice as wide as it is
   * high. Measured 0.562 / 0.515 / 0.535 desktop, 0.575 / 0.502 / 0.533 phone —
   * comfortably inside. The new CEILING is the load-bearing half: it is what
   * fails the "grow it straight up into a tall skinny chain" family, which is
   * the way an upward layout goes wrong.
   *
   * The FRAME-HEIGHT SHARE went 0.55 → 0.50 with the fan, and is now **0.75**,
   * which is the whole point of tightening the entry sweep. It measures how much
   * of the frame the drawing actually occupies vertically, i.e. it is the dead
   * band stated as a ratio, and it is the bar that would have caught the band in
   * the first place had it been set honestly. Under the 1.5-turn sweep the frame
   * was fitted to what is very nearly a DISC, so it came out very nearly square
   * around a drawing twice as wide as it is tall: 0.532 desktop, 0.569 phone —
   * ~149 CSS px of empty paper above and below. At a quarter turn the swept
   * union hugs the drawing and the same measurement is **0.851 desktop, 0.903
   * phone**. The floor is set at 0.75 rather than at the measurement, so the
   * type scale still has somewhere to move, but it is now high enough that
   * putting the 540° sweep back fails this test rather than merely making the
   * section 224px taller in silence.
   *
   * What is asserted, then: the aspect stays inside a stated window, the drawing
   * fills a real share of the frame on EACH axis, and it is CENTRED, so whatever
   * whitespace the sweep does cost is spent symmetrically instead of shoved to
   * one side. The left-to-right seating family — which grows upward and keeps
   * children with their parents, but puts a two-step arm on the vertical and the
   * leaf beside it — measures 13% off-centre and fails this.
   *
   * The VERTICAL off-centre number moved 2.1% → 4.2% (desktop; 1.8% → 3.9%
   * phone) and the 5% bar did not, which is the constraint that picked the
   * quarter turn over a third of one. The sweep's headroom is one-sided — the
   * fan's tips lift past the settled top when they rotate through the vertical,
   * while nothing swings below the course code — so every degree of rotation
   * buys frame at the top only and slides the drawing down inside it. At 0.3
   * turns this reads 5.4% and fails.
   */
  describe('the settled graph is a sane shape, centred in its frame', () => {
    for (const view of GRAPH_VIEWS) {
      for (const graph of COURSE_GRAPHS) {
        it(`${graph.id} at maxRadius ${view.maxRadius}`, () => {
          const points = radialLayout(graph, view.w, view.h, view.maxRadius);
          let l = Infinity;
          let r = -Infinity;
          let t = Infinity;
          let b = -Infinity;
          for (const n of graph.nodes) {
            const p = points.get(n.id)!;
            const isRoot = n.id === graph.rootId;
            const e = drawnExtent(
              view,
              n.label,
              isRoot,
              p.x,
              p.y,
              isRoot ? view.rootR : view.nodeR,
              1,
            );
            l = Math.min(l, e.left);
            r = Math.max(r, e.right);
            t = Math.min(t, e.top);
            b = Math.max(b, e.bottom);
          }
          const aspect = (b - t) / (r - l);
          expect(aspect, 'settled aspect').toBeGreaterThanOrEqual(0.4);
          expect(aspect, 'settled aspect').toBeLessThanOrEqual(0.8);
          // Measured: 0.841–0.964 wide, 0.851–0.903 tall.
          expect((r - l) / view.fit.w, 'share of the frame width').toBeGreaterThan(0.75);
          expect((b - t) / view.fit.h, 'share of the frame height').toBeGreaterThan(0.75);
          // Centred: measured ≤ 3.9% of the width, ≤ 4.2% of the height.
          expect(
            Math.abs((l + r) / 2 - (view.fit.x + view.fit.w / 2)) / view.fit.w,
            'horizontal off-centre',
          ).toBeLessThan(0.05);
          expect(
            Math.abs((t + b) / 2 - (view.fit.y + view.fit.h / 2)) / view.fit.h,
            'vertical off-centre',
          ).toBeLessThan(0.05);
        });
      }
    }
  });
});

/**
 * #344 visual 3 — the fit is computed ONCE across all three fixtures, not per
 * graph. The `<svg>` is `h-auto`, so a per-graph box would change the section's
 * height every time a visitor clicked a course chip.
 */
describe('fitViewBox — one stable frame for every course', () => {
  for (const view of GRAPH_VIEWS) {
    it(`${viewBoxAttr(view.fit)} contains every single-course fit`, () => {
      for (const graph of COURSE_GRAPHS) {
        const solo = fitViewBox([graph], view);
        expect(solo.x, graph.id).toBeGreaterThanOrEqual(view.fit.x);
        expect(solo.y, graph.id).toBeGreaterThanOrEqual(view.fit.y);
        expect(solo.x + solo.w, graph.id).toBeLessThanOrEqual(view.fit.x + view.fit.w);
        expect(solo.y + solo.h, graph.id).toBeLessThanOrEqual(view.fit.y + view.fit.h);
      }
    });
  }

  it('is measured off the content, not the layout box', () => {
    // The shipped bug: `viewBox="0 0 900 560"` around content 578 units wide.
    expect(DESKTOP_VIEW.fit.w).toBeLessThan(DESKTOP_VIEW.w);
    expect(DESKTOP_VIEW.fit.h).toBeLessThan(DESKTOP_VIEW.h);
    expect(viewBoxAttr(DESKTOP_VIEW.fit)).toBe('161 114 582 334');
    expect(viewBoxAttr(MOBILE_VIEW.fit)).toBe('-32 40 429 230');
  });
});

/**
 * #344 visual 4 — labels must not land on top of each other, on another node's
 * dot, or on an edge they have nothing to do with.
 *
 * A node's OWN edges are excluded: they radiate from the dot the label belongs
 * to, so a short crossing is unavoidable and is exactly what the halo is for.
 * Everything else is a real collision, and the phone breakpoint was losing this
 * before the retune — "Distributions" and "Hypothesis Tests" overlapped by ~21
 * CSS px of solid text at 390px.
 *
 * Deliberately measured against the dot's bounding SQUARE, i.e. pessimistically:
 * clearing the square clears the circle.
 */
describe('settled frame — no foreign label collisions', () => {
  type Box = { l: number; r: number; t: number; b: number };
  /** Signed separation: negative means the boxes overlap. */
  const gap = (a: Box, z: Box) =>
    Math.max(z.l - a.r, a.l - z.r, z.t - a.b, a.t - z.b);

  /** The label alone — `drawnExtent` unions in the dot, which is not wanted here. */
  function labelBox(
    view: (typeof GRAPH_VIEWS)[number],
    label: string,
    isRoot: boolean,
    p: { x: number; y: number },
    r: number,
  ): Box {
    const half = (label.length * MONO_ADVANCE_EM * view.font) / 2 + view.labelHalo / 2;
    const baseline = labelBaselineY(view, isRoot, p.y, r);
    return {
      l: p.x - half,
      r: p.x + half,
      t: baseline - view.font * 0.73 - view.labelHalo / 2,
      b: baseline + view.font * 0.25 + view.labelHalo / 2,
    };
  }

  for (const view of GRAPH_VIEWS) {
    for (const graph of COURSE_GRAPHS) {
      it(`${graph.id} at maxRadius ${view.maxRadius} keeps every label clear`, () => {
        const pts = radialLayout(graph, view.w, view.h, view.maxRadius);
        const radius = (id: string) => (id === graph.rootId ? view.rootR : view.nodeR);
        const boxes = new Map(
          graph.nodes.map((n) => [
            n.id,
            labelBox(view, n.label, n.id === graph.rootId, pts.get(n.id)!, radius(n.id)),
          ]),
        );

        for (const a of graph.nodes) {
          for (const b of graph.nodes) {
            if (a.id === b.id) continue;
            // label ↔ label
            expect(
              gap(boxes.get(a.id)!, boxes.get(b.id)!),
              `${a.id} label vs ${b.id} label`,
            ).toBeGreaterThan(0);
            // label ↔ someone else's dot
            const p = pts.get(b.id)!;
            const r = radius(b.id);
            expect(
              gap(boxes.get(a.id)!, { l: p.x - r, r: p.x + r, t: p.y - r, b: p.y + r }),
              `${a.id} label vs ${b.id} dot`,
            ).toBeGreaterThan(0);
          }

          // label ↔ an edge it is not an endpoint of
          for (const e of graph.edges) {
            if (e.source === a.id || e.target === a.id) continue;
            const p1 = pts.get(e.source)!;
            const p2 = pts.get(e.target)!;
            const box = boxes.get(a.id)!;
            let closest = Infinity;
            for (let i = 0; i <= 400; i++) {
              const t = i / 400;
              const x = p1.x + (p2.x - p1.x) * t;
              const y = p1.y + (p2.y - p1.y) * t;
              closest = Math.min(closest, Math.max(box.l - x, x - box.r, box.t - y, y - box.b));
            }
            expect(closest, `${a.id} label vs edge ${e.source}->${e.target}`).toBeGreaterThan(0);
          }
        }
      });
    }
  }
});

/**
 * #344 review #3 — the demo was one 900×560 viewBox at every width, which at a
 * 390px phone viewport is a uniform 0.38 scale: 4.6 CSS px labels and 10.6 CSS
 * px dots. These pin the sizes the mobile view actually resolves to, in the
 * units a visitor sees — and they are the unit-test twin of the Playwright gate
 * in `e2e/landing-graph.spec.ts` (≥11px labels, ≥20px dots, >170px tall).
 */
describe('GraphView sizing at a 390px viewport', () => {
  /**
   * 390px viewport − `px-6` (24px each side) − the 10px scrollbar globals.css
   * paints (`*::-webkit-scrollbar { width: 10px }`) = the section's content
   * box. Deliberately the pessimistic number: the E2E measures the real
   * `getBoundingClientRect().width`, so modelling it 10px narrower keeps this
   * test the stricter of the two.
   */
  const CONTENT_PX = 390 - 48 - 10;

  it('renders legible labels and dots on a phone', () => {
    const scale = CONTENT_PX / MOBILE_VIEW.fit.w;
    expect(scale).toBeCloseTo(0.7739, 4);
    // 12.38 CSS px labels, 23.22 CSS px dot diameter, 178.0 CSS px of frame.
    // The phone geometry is still bracketed from BELOW by a label collision
    // (which wants a bigger ring) and from ABOVE by the type gate (which wants a
    // smaller frame), and tightening the entry sweep moved both the right way at
    // once: the frame narrowed 443 → 429 units, so every unit renders bigger.
    // Margins are now +1.38px and +3.22px, against +0.99px and +2.48px under the
    // 1.5-turn sweep and +0.23px / +0.85px under the downward tree.
    expect(MOBILE_VIEW.font * scale).toBeGreaterThanOrEqual(11);
    expect(2 * MOBILE_VIEW.nodeR * scale).toBeGreaterThanOrEqual(20);
    // THE THIRD BAR CHANGED WHAT IT MEASURES, and it is worth being explicit.
    // It used to be `fit.h * scale >= 260` — the FRAME's rendered height — and
    // it was written to fail the "213px smudge" the hardcoded 900×560 viewBox
    // rendered at this viewport. That reading only worked while the frame was
    // mostly empty paper: fitting to a 1.5-turn sweep reserved 64 and 54 CSS px
    // of band above and below a 156px-tall drawing, and the bar was passing on
    // the band. The quarter turn spends 16 and 2 instead, so the frame is 178px
    // and the DRAWING inside it is 160.7 — bigger than it was, in a box 95px
    // shorter. So: assert the drawing, which is what "not a smudge" meant, and
    // keep a floor on the frame that a genuinely tiny graph still fails.
    expect(MOBILE_VIEW.fit.h * scale, 'rendered frame height').toBeGreaterThanOrEqual(170);
    expect(settledHeight(MOBILE_VIEW) * scale, 'rendered drawing height').toBeGreaterThanOrEqual(
      150,
    );
  });

  it('documents why the desktop view is still not a phone view', () => {
    // Not an aspiration — the reason `useIsMobile` swaps views at all, kept
    // here so a future "just use one viewBox everywhere" change has to argue
    // with it. The fit shrank the desktop box from 900 to 582 units, which
    // lifts a phone-rendered desktop label from 4.6 to 8.0 CSS px — still
    // nowhere near the 11px floor above.
    const scale = CONTENT_PX / DESKTOP_VIEW.fit.w;
    expect(DESKTOP_VIEW.font * scale).toBeLessThan(11);
    expect(2 * DESKTOP_VIEW.nodeR * scale).toBeLessThan(20);
  });
});
