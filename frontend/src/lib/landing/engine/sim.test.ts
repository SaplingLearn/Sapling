// @vitest-environment jsdom
/**
 * The drag field has to behave like part of the page, not a layer floating
 * over it. Three regressions this pins, all of them things the sim used to do:
 *
 *  - a cluster inside a pinned act drifted up to 150px against the scroll;
 *  - the sim kept integrating while the page scrolled, so every node wandered
 *    a few px/frame under a moving page;
 *  - nodes were clamped to their svg's viewBox, which walled the drag ~900px
 *    sideways and ~1600px up/down of the cluster's home.
 *
 * jsdom has no layout, so the fixture supplies the geometry itself: rects are
 * derived from a virtual scroll offset and from each cluster's own transform,
 * which is the one thing the sim actually writes. The numbers match the real
 * page — a 1974x3418 svg on viewBox "-900 -1600 1974 3418", so one viewBox
 * unit is one px and local (x, y) lands at (clusterX + x, clusterY + y).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { createSim, type SimController } from './sim';

const VIEW_W = 1440;
const VIEW_H = 900;

/** Where the field sits in the document, before any scrolling. */
const FIELD_DOC_TOP = 500;
/** The cluster's origin in viewport space at scroll 0. Right of centre, so a
 *  drag to the left edge clears the old -900 viewBox wall. */
const CLUSTER_X = 1200;
const CLUSTER_Y = 700;

/** The svg's own box, and the negative margins that recentre it. */
const SVG_W = 1974;
const SVG_H = 3418;
const VB_X = -900;
const VB_Y = -1600;

/** The old viewBox clamp, kept here as the thing the drag must now clear. */
const OLD_WALL_LEFT = VB_X;
const OLD_WALL_BOTTOM = VB_Y + SVG_H;

interface World {
  scrollY: number;
  /** Rect stubs consult this, so a "scroll" moves the field like a real one. */
  fieldSticky: boolean;
}

/** Tall enough to pin for several viewports, like a real act. */
const SECTION_H = 3000;

let world: World;
let root: HTMLDivElement;
let section: HTMLElement;
let field: HTMLDivElement;
let cluster: HTMLElement;
let svg: SVGSVGElement;
let rings: SVGCircleElement[];
let sim: SimController;
let clock: number;
let scrollBySpy: ReturnType<typeof vi.fn>;

function rect(el: Element, get: () => { left: number; top: number; width: number; height: number }) {
  (el as HTMLElement).getBoundingClientRect = () => {
    const r = get();
    return {
      ...r, x: r.left, y: r.top,
      right: r.left + r.width, bottom: r.top + r.height,
      toJSON() { return r; },
    } as DOMRect;
  };
}

/** The cluster's live viewport origin: its transform once the sim owns it,
 *  its static position before that. */
function clusterOrigin(): { x: number; y: number } {
  const m = /translate3d\(([-\d.]+)px,\s*([-\d.]+)px/.exec(cluster.style.transform || '');
  if (m) return { x: parseFloat(m[1]), y: parseFloat(m[2]) };
  return { x: CLUSTER_X, y: fieldTop() + (CLUSTER_Y - FIELD_DOC_TOP) };
}

function fieldTop(): number {
  // A sticky field stays pinned at the top of the viewport; a static one
  // scrolls with the document. Both are exercised.
  return world.fieldSticky ? 0 : FIELD_DOC_TOP - world.scrollY;
}

/** Where a node's local coordinate lands on screen. */
function screenOf(n: { x: number; y: number }): { x: number; y: number } {
  const o = clusterOrigin();
  return { x: o.x + n.x, y: o.y + n.y };
}

function ringLocal(i: number): { x: number; y: number } {
  return {
    x: parseFloat(rings[i].getAttribute('cx') || '0'),
    y: parseFloat(rings[i].getAttribute('cy') || '0'),
  };
}

function buildFixture(): void {
  root = document.createElement('div');
  field = document.createElement('div');
  field.className = 'drag-field';

  section = document.createElement('section');
  section.appendChild(field);
  root.appendChild(section);
  document.body.appendChild(root);

  // Three nodes, in the strict glow -> ring -> label order the sim binds by.
  field.innerHTML = `
    <span data-dragnode="1">
      <span data-dragpuck="1">
        <svg width="${SVG_W}" height="${SVG_H}" viewBox="${VB_X} ${VB_Y} ${SVG_W} ${SVG_H}">
          <line x1="76" y1="44" x2="106" y2="104" stroke-width="1.1"></line>
          <line x1="76" y1="44" x2="30" y2="110" stroke-width="0.8"></line>
          <circle cx="76" cy="44" r="26"></circle>
          <circle data-ring="1" data-sim="1" cx="76" cy="44" r="18"></circle>
          <text x="76" y="77">MA 242</text>
          <circle cx="106" cy="104" r="18"></circle>
          <circle data-ring="1" data-sim="1" cx="106" cy="104" r="10"></circle>
          <text x="106" y="126">series</text>
          <circle cx="30" cy="110" r="18"></circle>
          <circle data-ring="1" data-sim="1" cx="30" cy="110" r="10"></circle>
          <text x="30" y="132">vectors</text>
        </svg>
      </span>
    </span>`;

  cluster = field.querySelector<HTMLElement>('[data-dragnode]')!;
  svg = field.querySelector('svg')!;
  rings = Array.from(svg.querySelectorAll<SVGCircleElement>('[data-sim]'));

  // jsdom's SVGSVGElement has no viewBox animated-value plumbing.
  Object.defineProperty(svg, 'viewBox', {
    value: { baseVal: { x: VB_X, y: VB_Y, width: SVG_W, height: SVG_H } },
    configurable: true,
  });

  // The act itself scrolls normally; only the field inside it pins. This rect
  // is what the old parallax read to decide how far to slide the cluster, so
  // it has to be real for the pinned-act test to mean anything.
  rect(section, () => ({
    left: 0, top: FIELD_DOC_TOP - world.scrollY, width: VIEW_W, height: SECTION_H,
  }));
  rect(field, () => ({ left: 0, top: fieldTop(), width: VIEW_W, height: VIEW_H }));
  // The cluster span shrink-wraps to the svg's box plus its negative margins;
  // the svg itself hangs 900/1600 up and to the left of that origin.
  rect(cluster, () => {
    const o = clusterOrigin();
    return { left: o.x, top: o.y, width: SVG_W + 2 * VB_X, height: SVG_H + 2 * VB_Y };
  });
  rect(svg, () => {
    const o = clusterOrigin();
    return { left: o.x + VB_X, top: o.y + VB_Y, width: SVG_W, height: SVG_H };
  });
}

/** A pointer event jsdom will dispatch — PointerEvent itself is unimplemented. */
function pointer(type: string, clientX: number, clientY: number): MouseEvent {
  const e = new MouseEvent(type, { clientX, clientY, bubbles: true, cancelable: true });
  Object.defineProperty(e, 'pointerId', { value: 7 });
  return e;
}

function scrollTo(y: number): void {
  world.scrollY = y;
  window.dispatchEvent(new Event('scroll'));
}

/** Run n frames, advancing the shared clock by one 60fps tick each. */
function frames(n: number): void {
  for (let i = 0; i < n; i++) {
    clock += 16;
    sim.step(VIEW_H, clock);
  }
}

beforeEach(() => {
  world = { scrollY: 0, fieldSticky: false };
  clock = 10_000;
  vi.spyOn(performance, 'now').mockImplementation(() => clock);
  Object.defineProperty(window, 'innerWidth', { value: VIEW_W, configurable: true });
  Object.defineProperty(window, 'innerHeight', { value: VIEW_H, configurable: true });

  // jsdom has no scrolling; wire scrollBy to the virtual world so autoscroll
  // moves the field exactly as a real scroll would.
  scrollBySpy = vi.fn((_x: number, y: number) => { scrollTo(world.scrollY + y); });
  Object.defineProperty(window, 'scrollBy', { value: scrollBySpy, configurable: true });

  buildFixture();
  sim = createSim();
  expect(sim.ensureInit(root)).toBe(true);
});

afterEach(() => {
  sim.destroy();
  root.remove();
  vi.restoreAllMocks();
});

describe('cluster anchoring', () => {
  it('sits at exactly field.rect + anchor, with nothing added', () => {
    frames(1);
    const o = clusterOrigin();
    expect(o.x).toBeCloseTo(CLUSTER_X, 1);
    expect(o.y).toBeCloseTo(CLUSTER_Y, 1);
  });

  it('translates 1:1 with a static field as the page scrolls', () => {
    frames(1);
    const before = clusterOrigin();
    scrollTo(420);
    frames(1);
    expect(clusterOrigin().y).toBeCloseTo(before.y - 420, 1);
    expect(clusterOrigin().x).toBeCloseTo(before.x, 1);
  });

  it('holds still with a pinned act instead of drifting against it', () => {
    // The regression: a sticky field used to subtract up to 150px of parallax
    // as its section scrolled through, so the cluster slid under the copy it
    // belongs to. A pinned field's rect does not move, so neither may the
    // cluster — at any depth into the section.
    sim.destroy();
    root.remove();
    world = { scrollY: 0, fieldSticky: true };
    buildFixture();
    field.style.position = 'sticky';
    sim = createSim();
    expect(sim.ensureInit(root)).toBe(true);

    frames(1);
    const pinnedAt = clusterOrigin();
    for (const y of [200, 900, 1800, 3000]) {
      scrollTo(y);
      frames(1);
      expect(clusterOrigin().x).toBeCloseTo(pinnedAt.x, 1);
      expect(clusterOrigin().y).toBeCloseTo(pinnedAt.y, 1);
    }
  });
});

describe('scroll freeze', () => {
  it('does not move a node while the page is scrolling', () => {
    // Settle first, so any movement during the scroll is unambiguous.
    frames(40);
    const before = rings.map((_, i) => ringLocal(i));

    for (let s = 1; s <= 12; s++) {
      scrollTo(s * 60);
      frames(3);
    }

    rings.forEach((_, i) => {
      expect(ringLocal(i).x).toBeCloseTo(before[i].x, 5);
      expect(ringLocal(i).y).toBeCloseTo(before[i].y, 5);
    });
  });

  it('breathes again once the page has been still for the quiet window', () => {
    frames(10);
    scrollTo(300);
    frames(3);
    const frozen = ringLocal(1);

    // Past SCROLL_QUIET_MS with no further scroll events.
    clock += 400;
    frames(30);

    const moved = ringLocal(1);
    expect(Math.hypot(moved.x - frozen.x, moved.y - frozen.y)).toBeGreaterThan(0);
  });

  it('still tracks the pointer while the page scrolls under it', () => {
    const start = screenOf(ringLocal(0));
    rings[0].dispatchEvent(pointer('pointerdown', start.x, start.y));
    window.dispatchEvent(pointer('pointermove', 300, 260));
    frames(2);

    // The node is pinned to a screen position, so scrolling the page must not
    // drag it off the cursor.
    for (let s = 1; s <= 6; s++) {
      scrollTo(s * 80);
      frames(2);
      const at = screenOf(ringLocal(0));
      expect(at.x).toBeCloseTo(300, 0);
      expect(at.y).toBeCloseTo(260, 0);
    }
  });
});

describe('drag reach', () => {
  it('clears the old viewBox wall on the way to the far edge', () => {
    const start = screenOf(ringLocal(0));
    rings[0].dispatchEvent(pointer('pointerdown', start.x, start.y));
    window.dispatchEvent(pointer('pointermove', 8, 300));
    frames(4);

    // Old behaviour: walled at the viewBox edge, ~900px left of home.
    expect(ringLocal(0).x).toBeLessThan(OLD_WALL_LEFT);
    // New behaviour: stops only at the viewport edge, and stays on screen.
    expect(screenOf(ringLocal(0)).x).toBeGreaterThanOrEqual(0);
    expect(screenOf(ringLocal(0)).x).toBeLessThan(60);
  });

  it('keeps a held node inside the viewport however far the pointer goes', () => {
    const start = screenOf(ringLocal(0));
    rings[0].dispatchEvent(pointer('pointerdown', start.x, start.y));

    for (const [px, py] of [[-4000, 400], [4000, 400], [700, -4000], [700, 4000]]) {
      window.dispatchEvent(pointer('pointermove', px, py));
      frames(3);
      const at = screenOf(ringLocal(0));
      expect(at.x).toBeGreaterThanOrEqual(0);
      expect(at.x).toBeLessThanOrEqual(VIEW_W);
      expect(at.y).toBeGreaterThanOrEqual(0);
      expect(at.y).toBeLessThanOrEqual(VIEW_H);
    }
  });

  it('carries a node down the document, past where the old clamp stopped', () => {
    const start = screenOf(ringLocal(0));
    rings[0].dispatchEvent(pointer('pointerdown', start.x, start.y));
    // Held in the bottom band: the page should scroll under the node.
    window.dispatchEvent(pointer('pointermove', 700, VIEW_H - 20));
    frames(120);

    expect(world.scrollY).toBeGreaterThan(1000);
    // Local coords grow as the anchor scrolls away; the old clamp stopped
    // this dead at the bottom of the viewBox.
    expect(ringLocal(0).y).toBeGreaterThan(OLD_WALL_BOTTOM);
    // ...and it is still on screen, under the cursor.
    expect(screenOf(ringLocal(0)).y).toBeLessThanOrEqual(VIEW_H);
    expect(screenOf(ringLocal(0)).y).toBeGreaterThan(VIEW_H - 100);
  });

  it('carries a node back up the document the same way', () => {
    scrollTo(4000);
    frames(2);
    const start = screenOf(ringLocal(0));
    rings[0].dispatchEvent(pointer('pointerdown', start.x, start.y));
    window.dispatchEvent(pointer('pointermove', 700, 20));
    frames(120);

    expect(world.scrollY).toBeLessThan(3000);
    expect(screenOf(ringLocal(0)).y).toBeGreaterThanOrEqual(0);
  });
});

describe('placement', () => {
  /** Grab node `i`, drag it to a screen point, and let go. */
  function dropAt(i: number, x: number, y: number): void {
    const start = screenOf(ringLocal(i));
    rings[i].dispatchEvent(pointer('pointerdown', start.x, start.y));
    window.dispatchEvent(pointer('pointermove', x, y));
    frames(3);
    window.dispatchEvent(pointer('pointerup', x, y));
  }

  it('leaves a dropped node exactly where it was put', () => {
    dropAt(1, 300, 200);
    const dropped = ringLocal(1);

    // Long enough for the link spring (34-86px rest length), the anchor
    // spring and a full breathing period to have reeled it back in.
    frames(1200);

    expect(ringLocal(1).x).toBeCloseTo(dropped.x, 3);
    expect(ringLocal(1).y).toBeCloseTo(dropped.y, 3);
  });

  it('stays put where the page put it, scrolling with its section', () => {
    dropAt(1, 300, 200);
    const onScreen = screenOf(ringLocal(1));
    frames(600);
    scrollTo(350);
    frames(20);
    // Moved with the page by exactly the scroll, and not a px more.
    expect(screenOf(ringLocal(1)).y).toBeCloseTo(onScreen.y - 350, 1);
    expect(screenOf(ringLocal(1)).x).toBeCloseTo(onScreen.x, 1);
  });

  it('does not drag the rest of the cluster along with it', () => {
    dropAt(1, 300, 200);
    frames(600);

    // Node 1 is hundreds of px away; node 2 stays home, inside the ~20px
    // envelope its breathing drift traces. A placed node that still pulled
    // would have towed it across the field.
    const placed = ringLocal(1);
    expect(Math.hypot(placed.x - 106, placed.y - 104)).toBeGreaterThan(200);
    const stayed = ringLocal(2);
    expect(Math.hypot(stayed.x - 30, stayed.y - 110)).toBeLessThan(30);
  });

  it('rejoins the cluster when dropped back where it started', () => {
    const start = screenOf(ringLocal(1));
    dropAt(1, 300, 200);
    frames(60);
    expect(Math.hypot(ringLocal(1).x - 106, ringLocal(1).y - 104)).toBeGreaterThan(200);

    // Pick it up and put it back inside the rejoin radius.
    const held = screenOf(ringLocal(1));
    rings[1].dispatchEvent(pointer('pointerdown', held.x, held.y));
    window.dispatchEvent(pointer('pointermove', start.x + 8, start.y + 8));
    frames(3);
    window.dispatchEvent(pointer('pointerup', start.x + 8, start.y + 8));
    frames(400);

    // Back in the simulation. Not at its old coordinates — the cluster's
    // equilibrium is the link rest lengths, not the layout it was authored
    // with — but back among its neighbours, and moving again.
    const settled = ringLocal(1);
    expect(Math.hypot(settled.x - 106, settled.y - 104)).toBeLessThan(80);
    frames(200);
    expect(Math.hypot(ringLocal(1).x - settled.x, ringLocal(1).y - settled.y)).toBeGreaterThan(0);
  });

  it('still draws its edges to wherever it was left', () => {
    dropAt(1, 300, 200);
    frames(120);
    const line = svg.querySelector('line')!;
    const at = ringLocal(1);
    // The first line runs root -> node 1; its far end tracks the placed node.
    expect(parseFloat(line.getAttribute('x2')!)).toBeCloseTo(at.x, 1);
    expect(parseFloat(line.getAttribute('y2')!)).toBeCloseTo(at.y, 1);
  });
});

describe('edge autoscroll', () => {
  it('leaves the page alone when the node is held away from the edges', () => {
    const start = screenOf(ringLocal(0));
    rings[0].dispatchEvent(pointer('pointerdown', start.x, start.y));
    window.dispatchEvent(pointer('pointermove', 700, VIEW_H / 2));
    frames(60);
    expect(scrollBySpy).not.toHaveBeenCalled();
    expect(world.scrollY).toBe(0);
  });

  it('leaves the page alone when nothing is being dragged', () => {
    frames(60);
    expect(scrollBySpy).not.toHaveBeenCalled();
  });

  it('accelerates toward the edge of the band', () => {
    const start = screenOf(ringLocal(0));
    rings[0].dispatchEvent(pointer('pointerdown', start.x, start.y));

    window.dispatchEvent(pointer('pointermove', 700, VIEW_H - 100));
    frames(1);
    const gentle = scrollBySpy.mock.calls.at(-1)![1];

    window.dispatchEvent(pointer('pointermove', 700, VIEW_H - 2));
    frames(1);
    const steep = scrollBySpy.mock.calls.at(-1)![1];

    expect(gentle).toBeGreaterThan(0);
    expect(steep).toBeGreaterThan(gentle);
  });

  it('stops scrolling as soon as the node is released', () => {
    const start = screenOf(ringLocal(0));
    rings[0].dispatchEvent(pointer('pointerdown', start.x, start.y));
    window.dispatchEvent(pointer('pointermove', 700, VIEW_H - 10));
    frames(10);
    const moved = world.scrollY;
    expect(moved).toBeGreaterThan(0);

    window.dispatchEvent(pointer('pointerup', 700, VIEW_H - 10));
    frames(30);
    expect(world.scrollY).toBe(moved);
  });
});
