/**
 * The layout is deterministic on purpose: the E2E lane parks the animation and
 * asserts against a laid-out frame, so identical input must give identical
 * coordinates on every run and in every environment.
 */
import { describe, it, expect } from 'vitest';

import { COURSE_GRAPHS } from './courseGraphs';
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
   * settled bounding box. `helixEntry` rotates a node up to 1.5 turns on the way
   * in, and the outer ring rests on the horizontal axis, so it passes ~0.925 ×
   * maxRadius above and below the centre at ~83% opacity — 215 desktop units,
   * against a settled vertical extent of 58.
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

      expect(sweptTop).toBeLessThan(settledTop);
      expect(sweptBottom).toBeGreaterThan(settledBottom);
      // Comfortably, not marginally: the sweep needs ~2× the settled height.
      expect(sweptBottom - sweptTop).toBeGreaterThan(1.5 * (settledBottom - settledTop));
      // …and the fitted frame is sized for the sweep, not for the rest state.
      expect(view.fit.h).toBeGreaterThanOrEqual(sweptBottom - sweptTop);
    });
  }
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
    expect(viewBoxAttr(DESKTOP_VIEW.fit)).toBe('159 42 578 498');
    expect(viewBoxAttr(MOBILE_VIEW.fit)).toBe('-19 5 394 319');
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
    expect(scale).toBeCloseTo(0.8426, 4);
    // 11.8 CSS px labels (was 4.56), 23.6 CSS px dot diameter (was 10.64),
    // 269 CSS px of graph height (was 213).
    expect(MOBILE_VIEW.font * scale).toBeGreaterThanOrEqual(11);
    expect(2 * MOBILE_VIEW.nodeR * scale).toBeGreaterThanOrEqual(20);
    expect(MOBILE_VIEW.fit.h * scale).toBeGreaterThanOrEqual(260);
  });

  it('documents why the desktop view is still not a phone view', () => {
    // Not an aspiration — the reason `useIsMobile` swaps views at all, kept
    // here so a future "just use one viewBox everywhere" change has to argue
    // with it. The fit shrank the desktop box from 900 to 578 units, which
    // lifts a phone-rendered desktop label from 4.6 to 6.9 CSS px — still
    // nowhere near the 11px floor above.
    const scale = CONTENT_PX / DESKTOP_VIEW.fit.w;
    expect(DESKTOP_VIEW.font * scale).toBeLessThan(11);
    expect(2 * DESKTOP_VIEW.nodeR * scale).toBeLessThan(20);
  });
});
