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

/**
 * The envelope a dropped node stays inside: its breathing, plus the small
 * share of an arm correction it yields (`PLACED_YIELD`). Measured at 3.7-14px
 * across these fixtures. The bound is what separates "alive where I left it"
 * from "wandered off"; it is deliberately not zero, because a node that
 * refused to yield at all would hold an arm stretched instead.
 */
const SWAY_PX = 18;

/**
 * Transient headroom on the arm ceiling while a placed node is being towed.
 *
 * Only during a drag, and only when the resisting end is itself placed:
 * `PLACED_YIELD` is deliberately small, so the solve walks such a node along
 * over a few frames rather than in one. Measured peaking ~4px over. Every
 * settled assertion uses the strict ceiling.
 */
const TOW_SLACK_PX = 12;

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

  describe('copy that pins inside a static field', () => {
    // The FAQ shape: the section (and its field) scroll all the way through,
    // but the question column is `sticky; top:110` and holds for
    // `grid - column` = 375px. The field's rect cannot see that, so CS 112 and
    // PH 150 slid 374px out from under the words. `data-drag-track` names the
    // column so the sim can add its travel back.
    const TRACK_OFFSET = 120;   // the column starts one section-padding down
    const STICKY_TOP = 110;
    const TRAVEL = 375;

    /** A real sticky child: free, then pinned, then free again. */
    function trackTop(): number {
      const natural = FIELD_DOC_TOP + TRACK_OFFSET - world.scrollY;
      if (natural >= STICKY_TOP) return natural;
      return Math.max(natural, Math.min(STICKY_TOP, natural + TRAVEL));
    }

    let track: HTMLElement;

    beforeEach(() => {
      sim.destroy();
      root.remove();
      world = { scrollY: 0, fieldSticky: false };
      buildFixture();

      track = document.createElement('div');
      track.setAttribute('data-drag-anchor', 'faq');
      rect(track, () => ({ left: 0, top: trackTop(), width: 392, height: 358 }));
      section.appendChild(track);
      field.dataset.dragTrack = '[data-drag-anchor="faq"]';

      sim = createSim();
      expect(sim.ensureInit(root)).toBe(true);
    });

    it('holds the cluster still for exactly as long as the copy pins', () => {
      frames(1);
      const gap = clusterOrigin().y - trackTop();

      // Through the approach, the whole pin, and out the far side.
      for (const y of [0, 200, 600, 1000, 1400, 1800, 2400, 3200]) {
        scrollTo(y);
        frames(1);
        expect(clusterOrigin().y - trackTop()).toBeCloseTo(gap, 1);
      }
    });

    it('still translates 1:1 before the copy has pinned at all', () => {
      frames(1);
      const before = clusterOrigin();
      scrollTo(100); // well short of the 110px sticky threshold
      frames(1);
      expect(clusterOrigin().y).toBeCloseTo(before.y - 100, 1);
    });

    it('leaves an untracked field alone', () => {
      // The mechanism is opt-in; newsletter and cta must keep the old maths.
      // Rebuilt rather than re-inited: destroy() takes the overlay the
      // clusters were re-homed into, so a second ensureInit finds none.
      sim.destroy();
      root.remove();
      world = { scrollY: 0, fieldSticky: false };
      buildFixture();
      sim = createSim();
      expect(sim.ensureInit(root)).toBe(true);

      frames(1);
      const before = clusterOrigin();
      scrollTo(1400); // deep inside where the copy would be pinned
      frames(1);
      expect(clusterOrigin().y).toBeCloseTo(before.y - 1400, 1);
    });
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

  it('follows the pointer anywhere, with no wall around the drag', () => {
    // This used to clamp the held node into the visible box. The clamp was
    // solving a real problem — see `repinHeld` — but it did it by walling off
    // where a node could be taken. The node now goes wherever the pointer
    // goes, which is what the real graph does.
    const start = screenOf(ringLocal(0));
    rings[0].dispatchEvent(pointer('pointerdown', start.x, start.y));

    for (const [px, py] of [[-4000, 400], [4000, 400], [700, -4000], [700, 4000]]) {
      window.dispatchEvent(pointer('pointermove', px, py));
      frames(3);
      const at = screenOf(ringLocal(0));
      expect(Math.hypot(at.x - px, at.y - py)).toBeLessThan(2);
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

  it('leaves a dropped node where it was put, inside its sway', () => {
    dropAt(1, 300, 200);
    const dropped = ringLocal(1);

    // Long enough for the link spring, the anchor spring and a full breathing
    // period to have reeled it back in if any of them were going to.
    frames(1200);

    // Not identical: a placed node keeps a third of the breathing drift, so
    // it breathes around the drop point rather than freezing on it. SWAY_PX
    // is the envelope that buys — anything beyond it is a walk, not a sway.
    expect(Math.hypot(ringLocal(1).x - dropped.x, ringLocal(1).y - dropped.y))
      .toBeLessThan(SWAY_PX);
  });

  it('stays put where the page put it, scrolling with its section', () => {
    dropAt(1, 300, 200);
    const onScreen = screenOf(ringLocal(1));
    frames(600);
    scrollTo(350);
    frames(20);
    // Moved with the page by the scroll, and not a px more than its sway.
    expect(Math.hypot(
      screenOf(ringLocal(1)).x - onScreen.x,
      screenOf(ringLocal(1)).y - (onScreen.y - 350),
    )).toBeLessThan(SWAY_PX);
  });

  it('drags the whole cluster after a moved puck, not just the puck', () => {
    // The cluster must react, and it must react through the forces rather
    // than being carried at a fixed offset. Both halves matter: an earlier
    // fix seated the concepts rigidly on the puck, which held the shape and
    // killed every bit of life in it.
    const root0 = ringLocal(0);
    const sat0 = ringLocal(1);

    const start = screenOf(root0);
    rings[0].dispatchEvent(pointer('pointerdown', start.x, start.y));
    // Mid-viewport, clear of the edge band, so nothing autoscrolls.
    window.dispatchEvent(pointer('pointermove', start.x + 260, VIEW_H / 2));

    // One frame in: the concept is towed by a spring, so it trails rather
    // than arriving. A fixed offset would already be exact.
    frames(1);
    const lag = Math.hypot(ringLocal(1).x - sat0.x, ringLocal(1).y - sat0.y);
    expect(lag).toBeLessThan(Math.hypot(ringLocal(0).x - root0.x, ringLocal(0).y - root0.y));

    // ...and it does follow: it ends up near the puck, at roughly the link's
    // rest length, not stranded back where it started.
    frames(240);
    const root = ringLocal(0);
    const sat = ringLocal(1);
    expect(Math.hypot(sat.x - sat0.x, sat.y - sat0.y)).toBeGreaterThan(100);
    expect(Math.hypot(sat.x - root.x, sat.y - root.y)).toBeLessThan(200);
  });

  it('treats a scroll under the drag as a camera move, not a force', () => {
    // The cluster is welded to its field and travels with the page, while the
    // held node is pinned to a pointer that has not moved. Left uncancelled
    // that difference lands on the link spring every frame and diverges:
    // measured stretching 59/104/60px to 243/488/207px through one autoscroll.
    const root0 = ringLocal(0);
    const sat0 = ringLocal(1);
    const rest = Math.hypot(sat0.x - root0.x, sat0.y - root0.y);

    const start = screenOf(root0);
    rings[0].dispatchEvent(pointer('pointerdown', start.x, start.y));
    window.dispatchEvent(pointer('pointermove', start.x, start.y));

    // Scroll a long way under a pointer that never moves. Nothing the visitor
    // did should change the cluster's shape.
    for (const y of [200, 500, 900, 1500, 2600, 4000]) {
      scrollTo(y);
      frames(20);
      const gap = Math.hypot(ringLocal(1).x - ringLocal(0).x, ringLocal(1).y - ringLocal(0).y);
      expect(Math.abs(gap - rest)).toBeLessThan(20);
    }
  });

  it('gathers a cluster back around its placed puck', () => {
    // Dropping the puck used to strand its concepts: the link force was
    // skipped the moment either end was placed, so the only pull left was
    // each concept's own spring back to the original layout. They crawled
    // home and left one long edge stretched across the field. A placed node
    // anchors the link now instead of leaving it, so the cluster re-forms
    // around wherever the puck was put.
    const satBefore = ringLocal(1);

    dropAt(0, 520, 380);
    frames(400);

    const root = ringLocal(0);
    const sat = ringLocal(1);
    // It came along...
    expect(Math.hypot(sat.x - satBefore.x, sat.y - satBefore.y)).toBeGreaterThan(100);
    // ...and sits at the link's rest length, not on a long branch. The real
    // graph's distance is `40 + (1 - strength) * 90`, so 130px is its ceiling.
    expect(Math.hypot(sat.x - root.x, sat.y - root.y)).toBeLessThan(200);
  });

  it('moves the rest of the cluster when one concept is taken', () => {
    // This replaces the opposite assertion. A placed node used to drop out of
    // every force, so a concept could be parked anywhere and its cluster
    // would not notice — which is the behaviour that reads as dead. Moving
    // one node is supposed to move the whole cluster, exactly as it does in
    // the real knowledge graph.
    const rootBefore = ringLocal(0);
    const otherBefore = ringLocal(2);

    dropAt(1, 300, 200);
    frames(400);

    // The puck is linked to the concept that was taken, so it follows...
    expect(Math.hypot(ringLocal(0).x - rootBefore.x, ringLocal(0).y - rootBefore.y))
      .toBeGreaterThan(50);
    // ...and the sibling, linked to the puck, comes with it.
    expect(Math.hypot(ringLocal(2).x - otherBefore.x, ringLocal(2).y - otherBefore.y))
      .toBeGreaterThan(50);
  });

  it('holds a short drag instead of springing back to its home', () => {
    // The regression this replaces: a drop within 70px of home counted as
    // "put back", so the node re-floated — spring retargeted to the original
    // spot and the breathing restarted. Short drags are most drags, so most
    // drags crawled home. Measured in a browser at 14px of travel still
    // climbing 4s after a 40px drag, against 0px for a 90px one.
    const start = ringLocal(1);
    const to = screenOf({ x: start.x + 18, y: start.y + 14 });
    dropAt(1, to.x, to.y);
    const dropped = ringLocal(1);

    // It really was a short one — well inside the radius that used to reel
    // it in — and it moved.
    expect(Math.hypot(dropped.x - start.x, dropped.y - start.y)).toBeLessThan(70);
    expect(Math.hypot(dropped.x - start.x, dropped.y - start.y)).toBeGreaterThan(1);

    // Long enough for the anchor spring and a full breathing period.
    frames(1200);
    expect(Math.hypot(ringLocal(1).x - dropped.x, ringLocal(1).y - dropped.y))
      .toBeLessThan(SWAY_PX);
  });

  it('keeps breathing once dropped, but only just', () => {
    const start = ringLocal(1);
    const to = screenOf({ x: start.x + 6, y: start.y + 6 });
    dropAt(1, to.x, to.y);
    const dropped = ringLocal(1);

    // A free node wanders ~20px over its 15s period. A placed one keeps a
    // third of that: enough that it is visibly alive, little enough that it
    // is still sitting where it was left. Dead still is the bug this pins —
    // a dropped node used to stop moving entirely.
    frames(900);
    const moved = Math.hypot(ringLocal(1).x - dropped.x, ringLocal(1).y - dropped.y);
    expect(moved).toBeGreaterThan(0);
    expect(moved).toBeLessThan(SWAY_PX);
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

describe('arm length', () => {
  /** Every rendered arm, measured off the <line> elements the sim writes. */
  function armLengths(): number[] {
    return Array.from(svg.querySelectorAll('line')).map((l) => Math.hypot(
      parseFloat(l.getAttribute('x2') || '0') - parseFloat(l.getAttribute('x1') || '0'),
      parseFloat(l.getAttribute('y2') || '0') - parseFloat(l.getAttribute('y1') || '0'),
    ));
  }

  // Pulling a concept has to behave exactly like pulling the puck. It did
  // not: the link spring answers a gap with a fraction of the correction, so
  // an arm under continuous load keeps opening, and dragging a concept out of
  // a cluster drew its arms into a line across the section. The constraint
  // has no idea which node is which, so both cases are the same test.
  it.each([['the puck', 0], ['a concept', 1]] as const)(
    'holds every arm to its drawn length while %s is dragged',
    (_what, ring) => {
      // Read before any frame runs: still the authored geometry.
      const drawn = armLengths();
      expect(drawn.every((d) => d > 0)).toBe(true);

      const start = screenOf(ringLocal(ring));
      rings[ring].dispatchEvent(pointer('pointerdown', start.x, start.y));

      // Yank it right across the viewport, sampling every frame — a fast drag
      // is exactly what outran the spring.
      for (let i = 1; i <= 40; i++) {
        window.dispatchEvent(pointer('pointermove', start.x - 20 * i, start.y + 12 * i));
        frames(1);
        armLengths().forEach((len, k) => {
          expect(len).toBeLessThanOrEqual(drawn[k] + 0.5);
        });
      }


      // And it still holds once everything settles after the drop.
      window.dispatchEvent(pointer('pointerup', start.x - 800, start.y + 480));
      frames(300);
      armLengths().forEach((len, k) => {
        expect(len).toBeLessThanOrEqual(drawn[k] + 0.5);
      });
    },
  );

  it('holds arms between two already-placed nodes', () => {
    // The case that survived the first ceiling. Every drop places a node, so
    // after a couple of drags most of a cluster is placed — and an arm with a
    // placed node at BOTH ends was skipped as immovable, which meant nothing
    // could ever shorten it. Seen as `CS 112 - Memoize` drawn clean across
    // the FAQ while the rest of that cluster sat together at the far end.
    const drawn = armLengths();

    // Place one node, then drag a second one a long way off.
    const first = screenOf(ringLocal(2));
    rings[2].dispatchEvent(pointer('pointerdown', first.x, first.y));
    window.dispatchEvent(pointer('pointermove', first.x - 260, first.y - 160));
    frames(5);
    window.dispatchEvent(pointer('pointerup', first.x - 260, first.y - 160));
    frames(30);

    const second = screenOf(ringLocal(1));
    rings[1].dispatchEvent(pointer('pointerdown', second.x, second.y));
    for (let i = 1; i <= 30; i++) {
      window.dispatchEvent(pointer('pointermove', second.x + 24 * i, second.y + 16 * i));
      frames(1);
      // A placed node resists rather than refuses (PLACED_YIELD), so towing
      // one takes a few frames and the ceiling can be a hair over mid-drag.
      // TOW_SLACK_PX is that transient; the steady state below is strict.
      armLengths().forEach((len, k) => expect(len).toBeLessThanOrEqual(drawn[k] + TOW_SLACK_PX));
    }
    window.dispatchEvent(pointer('pointerup', second.x + 720, second.y + 480));
    frames(300);
    armLengths().forEach((len, k) => expect(len).toBeLessThanOrEqual(drawn[k] + 0.5));
  });

  it('lets an arm fold up, so the sway survives', () => {
    // The ceiling only ever shortens. An arm that could not compress would
    // pin the cluster into a rigid frame and take the life out of it.
    const drawn = armLengths();
    frames(600);
    const now = armLengths();
    expect(now.some((len, k) => len < drawn[k] - 1)).toBe(true);
  });
});

describe('teardown and rebuild', () => {
  it('puts every cluster back in its field', () => {
    // `ensureInit` re-parents each cluster into a fixed overlay inside a shell
    // it appends to `root`. destroy() used to just drop the shell, which took
    // the clusters with it — they were left detached from the document.
    expect(cluster.parentElement).not.toBe(field);

    sim.destroy();

    expect(field.querySelectorAll('[data-dragnode]')).toHaveLength(1);
    expect(cluster.isConnected).toBe(true);
  });

  it('clears the inline styles it wrote on the way in', () => {
    sim.destroy();
    // Left behind, these make the next build measure every anchor against the
    // overlay-parked position rather than the designed one.
    expect(cluster.style.position).toBe('');
    expect(cluster.style.left).toBe('');
    expect(cluster.style.transform).toBe('');
  });

  it('removes its overlay shell from the page', () => {
    sim.destroy();
    expect(root.querySelector('.drag-shell')).toBeNull();
  });

  it('builds again on the same DOM after being destroyed', () => {
    // React StrictMode runs setup -> cleanup -> setup on the same nodes in dev.
    // With the clusters detached, this second ensureInit found no
    // `[data-dragnode]` and returned false for the rest of the session, so the
    // whole drag field was silently dead.
    sim.destroy();

    const rebuilt = createSim();
    expect(rebuilt.ensureInit(root)).toBe(true);

    // And it is a live sim, not just a truthy return: the rebuilt cluster is
    // seated at field.rect + anchor exactly as the first build was.
    sim = rebuilt;
    frames(1);
    const o = clusterOrigin();
    expect(o.x).toBeCloseTo(CLUSTER_X, 1);
    expect(o.y).toBeCloseTo(CLUSTER_Y, 1);
  });

  it('survives a second destroy', () => {
    sim.destroy();
    expect(() => sim.destroy()).not.toThrow();
  });
});
