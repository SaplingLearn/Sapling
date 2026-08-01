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
  helixEntry,
  radialLayout,
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
 * #344 review #4 — the bug this file should have caught during development.
 *
 * The entry path used to stretch the offset from the centre by up to 1.9×, so
 * against the real desktop layout the outer ring swung to y = 693 (133px past
 * the 560-unit viewBox edge), got chopped by the `<svg>` viewport, and crossed
 * back in at opacity ≈ 0.5 — plainly visible, and invisible in review only
 * because the animation was also playing off-screen (review #1).
 *
 * So: sweep `t` across the whole entry for every node of every fixture in every
 * view, and assert that the drawn extent — circle, and label baseline — never
 * leaves the viewBox.
 */
describe('helixEntry × radialLayout — nothing leaves the viewBox', () => {
  /**
   * Labels render in JetBrains Mono, whose advance width is 600/1000 em. The
   * text is `textAnchor="middle"`, so half the string hangs off each side of
   * the node's x. This is the constraint that actually sizes the mobile view:
   * the outer ring sits on the horizontal axis, so its labels are the first
   * thing that would run off the right edge.
   */
  const MONO_ADVANCE_EM = 0.6;
  const STEPS = 400;

  for (const view of GRAPH_VIEWS) {
    for (const graph of COURSE_GRAPHS) {
      it(`${graph.id} stays inside ${view.w}×${view.h} across the whole sweep`, () => {
        const points = radialLayout(graph, view.w, view.h, view.maxRadius);
        const centre = { x: view.w / 2, y: view.h / 2 };

        for (const n of graph.nodes) {
          const p = points.get(n.id)!;
          const r = n.id === graph.rootId ? view.rootR : view.nodeR;
          const halfLabel = (n.label.length * MONO_ADVANCE_EM * view.font) / 2;

          for (let i = 0; i <= STEPS; i++) {
            const t = i / STEPS;
            const h = helixEntry(p, centre, t);
            const dotR = r * h.scale;
            const where = `${graph.id}/${n.id} @ t=${t.toFixed(3)}`;

            // Circle.
            expect(h.x - dotR, `${where} left`).toBeGreaterThanOrEqual(0);
            expect(h.x + dotR, `${where} right`).toBeLessThanOrEqual(view.w);
            expect(h.y - dotR, `${where} top`).toBeGreaterThanOrEqual(0);
            expect(h.y + dotR, `${where} bottom`).toBeLessThanOrEqual(view.h);

            // Label: baseline sits at `y + r + labelGap`; leave a descender's
            // worth (0.25em) of room under it.
            expect(
              h.y + r + view.labelGap + view.font * 0.25,
              `${where} label baseline`,
            ).toBeLessThanOrEqual(view.h);
            expect(h.x - halfLabel, `${where} label left`).toBeGreaterThanOrEqual(0);
            expect(h.x + halfLabel, `${where} label right`).toBeLessThanOrEqual(view.w);
          }
        }
      });
    }
  }
});

/**
 * #344 review #3 — the demo was one 900×560 viewBox at every width, which at a
 * 390px phone viewport (342px content box after `px-6`) is a uniform 0.38 scale:
 * 4.6 CSS px labels and 10.6 CSS px dots. These pin the sizes the mobile view
 * actually resolves to, in the units a visitor sees.
 */
describe('GraphView sizing at a 390px viewport', () => {
  /** 390px viewport − `px-6` (24px each side) = the section's content box. */
  const CONTENT_PX = 390 - 48;

  it('renders legible labels and dots on a phone', () => {
    const scale = CONTENT_PX / MOBILE_VIEW.w;
    expect(scale).toBeCloseTo(0.95, 4);
    // 12.35 CSS px labels (was 4.56), 22.8 CSS px dot diameter (was 10.64),
    // 285 CSS px of graph height (was 213).
    expect(MOBILE_VIEW.font * scale).toBeGreaterThanOrEqual(11);
    expect(2 * MOBILE_VIEW.nodeR * scale).toBeGreaterThanOrEqual(20);
    expect(MOBILE_VIEW.h * scale).toBeGreaterThanOrEqual(260);
  });

  it('documents what the desktop view resolved to on the same phone', () => {
    // Not an aspiration — the numbers the bug produced, kept here so a future
    // "just use one viewBox everywhere" change has to argue with them.
    const scale = CONTENT_PX / DESKTOP_VIEW.w;
    expect(DESKTOP_VIEW.font * scale).toBeLessThan(5); // 4.56 CSS px labels
    expect(DESKTOP_VIEW.h * scale).toBeLessThan(220); // 212.8 CSS px tall
  });
});
