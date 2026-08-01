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

  it('puts the root at the centre', () => {
    const p = radialLayout(G, 800, 500);
    expect(p.get(G.rootId)).toEqual({ x: 400, y: 250 });
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
   * CRITERION 3 — the invariant the previous wave established, carried over
   * unchanged. The ring phase used to be a half slot on alternate depths, which
   * on a 2-node ring (`step = π`, every fixture at depth 2 back then) resolved
   * to exactly {0, π}: both outer nodes dead on the horizontal axis.
   *
   * The tree only phases ONE ring — depth 1 — but deeper nodes inherit their
   * parent's heading when they are lone children, so the invariant has to hold
   * for them too. Asserted as an angle off the horizontal, not as a coordinate.
   */
  it('never lands a node on the horizontal axis through the centre', () => {
    for (const graph of COURSE_GRAPHS) {
      for (const view of GRAPH_VIEWS) {
        const pts = radialLayout(graph, view.w, view.h, view.maxRadius);
        for (const n of graph.nodes) {
          if (n.id === graph.rootId) continue;
          const p = pts.get(n.id)!;
          const dx = p.x - view.w / 2;
          const dy = p.y - view.h / 2;
          // |sin| of the angle off the horizontal axis. The old rule measured
          // exactly 0 on both depth-2 nodes; every node now measures 0.5 — 30°
          // off, the tightest angle either ring produces.
          expect(
            Math.abs(dy) / Math.hypot(dx, dy),
            `${graph.id}/${n.id} at maxRadius ${view.maxRadius}`,
          ).toBeGreaterThan(0.4);
        }
      }
    }
  });

  /**
   * …and the invariant `ringPhase` actually claims, which is stronger than the
   * three fixtures: for a ring of ANY size the angles are odd multiples of
   * `π/(2·count)`, so the closest one can ever come to the horizontal axis is
   * one such step. Swept over ring sizes 1…24 on synthetic star graphs — the
   * cheapest way to build a ring of a given size — with the count-aware floor
   * rather than a flat number, because a flat number is only meaningful for the
   * ring sizes that happen to ship today.
   */
  it('holds the no-horizontal invariant at any ring size', () => {
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
      // Half a slot of the ring's own quarter-slot grid, minus float slop.
      const floor = Math.sin(Math.PI / (2 * count)) * 0.999;
      for (let i = 0; i < count; i++) {
        const p = pts.get(`n${i}`)!;
        const sin = Math.abs(p.y - 280) / Math.hypot(p.x - 450, p.y - 280);
        expect(sin, `ring of ${count}, node ${i}`).toBeGreaterThan(floor);
      }
    }
  });

  /**
   * The wedge rule, which no shipped fixture exercises — every parent below the
   * root has exactly one child, so every arm is collinear with the centre. This
   * pins what happens when one doesn't: siblings SHARE their parent's angular
   * span, evenly and symmetrically about the parent's own outward direction, so
   * a branchy graph fans out instead of stacking on one ray.
   *
   * (It replaces the old "breaks radial spokes when two rings hold the same node
   * count" test, whose subject — a half-slot rotation applied to the SECOND
   * concentric ring — no longer exists: there are no rings past depth 1.)
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
    // Direction from `a` to each child, measured off `a` — the wedge's own axis
    // is the direction from the centre to `a`.
    const bearing = (id: string) => Math.atan2(pts.get(id)!.y - a.y, pts.get(id)!.x - a.x);
    const outward = Math.atan2(a.y - 280, a.x - 450);
    // `a` and `b` split the circle in two, so `a` owns a π wedge; three children
    // take the centres of three π/3 slices: −π/3, 0, +π/3 off the outward axis.
    expect(bearing('a1') - outward).toBeCloseTo(-Math.PI / 3, 6);
    expect(bearing('a2') - outward).toBeCloseTo(0, 6);
    expect(bearing('a3') - outward).toBeCloseTo(Math.PI / 3, 6);
    // Symmetric about the axis, and all still one ring step out.
    for (const id of ['a1', 'a2', 'a3']) {
      expect(Math.hypot(pts.get(id)!.x - a.x, pts.get(id)!.y - a.y), id).toBeCloseTo(116, 6);
    }
    // A child pushed off its parent's outward direction lands INSIDE maxRadius.
    for (const id of ['a1', 'a3']) {
      expect(Math.hypot(pts.get(id)!.x - 450, pts.get(id)!.y - 280), id).toBeLessThan(232);
    }
  });

  it('keeps the default maxRadius at the old inscribed-circle rule', () => {
    // The `maxRadius` parameter was added for the mobile view (#344 review #3).
    // Its default has to reproduce the desktop geometry this branch was
    // designed against byte-for-byte, or every existing frame shifts.
    expect(radialLayout(G, 900, 560)).toEqual(
      radialLayout(G, 900, 560, Math.min(900, 560) / 2 - 48),
    );
    expect(DESKTOP_VIEW.maxRadius).toBe(Math.min(DESKTOP_VIEW.w, DESKTOP_VIEW.h) / 2 - 48);
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

  it('rotates around the centre on the way in — the helix', () => {
    const mid = helixEntry(target, centre, 0.5);
    const straight = {
      x: centre.x + (target.x - centre.x) * easeOutCubic(0.5),
      y: centre.y + (target.y - centre.y) * easeOutCubic(0.5),
    };
    const off = Math.hypot(mid.x - straight.x, mid.y - straight.y);
    expect(off).toBeGreaterThan(10);
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
   * it, and that is precisely the clipping bug. So: prove the sweep leaves the
   * settled bounding box, and by how much. `helixEntry` rotates a node up to
   * 1.5 turns on the way in, so every outer node passes through every direction
   * before it lands.
   *
   * The MARGIN is what this asserts, in units, on each side. It used to be
   * stated as a ratio ("the sweep needs ~2× the settled height"), which was only
   * ever a proxy for "a settled fit would clip" and moved for reasons that had
   * nothing to do with clipping. Measured on each side: desktop 91.1 / 104.7,
   * mobile 63.6 / 73.5 — wider under the radial tree than under the rings
   * (59.0 / 59.3 and 33.5 / 33.5), because a three-branch tree is a wide, short
   * object sitting inside a circular sweep.
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

      // Comfortably, not marginally, and on BOTH sides: a frame fitted to the
      // rest state would chop this much off the top and bottom of the assembly,
      // live, at ~83% opacity.
      expect(settledTop - sweptTop).toBeGreaterThan(25);
      expect(sweptBottom - settledBottom).toBeGreaterThan(25);
      // …and the fitted frame is sized for the sweep, not for the rest state.
      expect(view.fit.h).toBeGreaterThanOrEqual(sweptBottom - sweptTop);
      expect(view.fit.h).toBeGreaterThan(settledBottom - settledTop);
    });
  }

  /**
   * CRITERION 4 — the settled drawing has to be a SANE SHAPE, sitting in the
   * middle of the frame it is given.
   *
   * The bar this replaces asked for aspect ≥ 0.60 and ≥ 0.70 of the frame
   * height, which the ring layout met (0.91–1.01 / 0.73) while putting children
   * nowhere near their parents. The radial tree cannot meet the height bar and
   * should not be asked to: three children 120° apart, two of them carrying a
   * second segment, make an object 1.73× as wide as it is tall, and the frame
   * is fitted to a near-circular sweep. Measured: aspect 0.626 / 0.575 / 0.597
   * desktop, 0.634 / 0.558 / 0.590 phone; 0.83–0.92 of the frame's WIDTH
   * against the ring layout's 0.71–0.79, and 0.56–0.60 of its height.
   *
   * So the assertions are: the aspect stays inside a stated window (a
   * re-flattening to the old 0.40, or a tall skinny chain, still fails), the
   * drawing fills a real share of the frame in EACH axis, and — the part the
   * height bar was really standing in for — it is CENTRED, so whatever
   * whitespace the sweep costs is spent symmetrically instead of shoved to one
   * side. The ring-phase family that keeps children with their parents but
   * seats a branch at 12 o'clock measures 10.4% off-centre and fails this.
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
          expect(aspect, 'settled aspect').toBeGreaterThanOrEqual(0.55);
          expect(aspect, 'settled aspect').toBeLessThanOrEqual(1.1);
          // Measured: 0.81–0.92 wide, 0.56–0.60 tall.
          expect((r - l) / view.fit.w, 'share of the frame width').toBeGreaterThan(0.75);
          expect((b - t) / view.fit.h, 'share of the frame height').toBeGreaterThan(0.55);
          // Centred: measured ≤ 3.4% of the width, ≤ 1.4% of the height.
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
    expect(viewBoxAttr(DESKTOP_VIEW.fit)).toBe('165 48 541 498');
    expect(viewBoxAttr(MOBILE_VIEW.fit)).toBe('-38 -11 414 356');
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
 * in `e2e/landing-graph.spec.ts` (≥11px labels, ≥20px dots, >260px tall).
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
    expect(scale).toBeCloseTo(0.8019, 4);
    // 11.23 CSS px labels, 20.85 CSS px dot diameter, 285.5 CSS px of graph
    // height. TIGHTER than the ring layout's 12.77 / 25.54 / 301.0, and
    // deliberately so: see `MOBILE_VIEW`. A 13-character label at this type
    // scale is 1.34× the ring step, so the phone geometry is bracketed from
    // BELOW by the label-vs-child-dot collision (which wants a bigger ring) and
    // from ABOVE by this gate (which wants a smaller frame), and the window
    // between them is about four units of ring wide. There is no slack here to
    // spend: any future type-scale nudge has to re-solve both at once.
    expect(MOBILE_VIEW.font * scale).toBeGreaterThanOrEqual(11);
    expect(2 * MOBILE_VIEW.nodeR * scale).toBeGreaterThanOrEqual(20);
    expect(MOBILE_VIEW.fit.h * scale).toBeGreaterThanOrEqual(260);
  });

  it('documents why the desktop view is still not a phone view', () => {
    // Not an aspiration — the reason `useIsMobile` swaps views at all, kept
    // here so a future "just use one viewBox everywhere" change has to argue
    // with it. The fit shrank the desktop box from 900 to 526 units, which
    // lifts a phone-rendered desktop label from 4.6 to 7.6 CSS px — still
    // nowhere near the 11px floor above.
    const scale = CONTENT_PX / DESKTOP_VIEW.fit.w;
    expect(DESKTOP_VIEW.font * scale).toBeLessThan(11);
    expect(2 * DESKTOP_VIEW.nodeR * scale).toBeLessThan(20);
  });
});
