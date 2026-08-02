// @vitest-environment jsdom
/**
 * The parked frame is the contract. Reduced-motion visitors and the E2E lane
 * both get this render, so "parked" has to mean laid out and readable — not
 * blank and not mid-assembly.
 */
import React from 'react';
import { act } from 'react';
import { renderToString } from 'react-dom/server';
import { hydrateRoot, type Root } from 'react-dom/client';
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { render, screen, cleanup, fireEvent } from '@testing-library/react';

import KnowledgeGraphDemo, { ENGAGED_HEADLINE_OPACITY } from './KnowledgeGraphDemo';
import { COURSE_GRAPHS, TIER_COLOR } from './courseGraphs';
import { DESKTOP_VIEW, MOBILE_VIEW, viewBoxAttr } from './layout';
import { __resetReducedMotionStoreForTests } from '@/lib/usePrefersReducedMotion';
import { __resetMediaStoresForTests } from '@/lib/useIsMobile';

afterEach(cleanup);

// `usePrefersReducedMotion` caches its `MediaQueryList` at module scope (by
// design — production wants one shared subscription, not one per consumer).
// Under vitest that cache survives across `it()` blocks in this file, so a
// test that installs its own local `window.matchMedia` — like the two below
// that swap it mid-run — would silently inherit whatever a *previous* test's
// render already warmed the cache with instead of its own override. Cold
// start every test so each one's `window.matchMedia` (whatever it is: the
// `vitest.setup.ts` default, or a local override) is what actually gets
// queried.
beforeEach(() => {
  __resetReducedMotionStoreForTests();
  // Same cache-warming hazard as above, for the `useIsMobile` store the
  // component now consults to pick its viewBox (#344 review #3).
  __resetMediaStoresForTests();
});

describe('KnowledgeGraphDemo', () => {
  it('renders a chip per course, with the first selected', () => {
    render(<KnowledgeGraphDemo />);
    for (const g of COURSE_GRAPHS) {
      expect(screen.getByTestId(`landing-graph-chip-${g.id}`)).toBeInTheDocument();
    }
    expect(
      screen.getByTestId(`landing-graph-chip-${COURSE_GRAPHS[0].id}`),
    ).toHaveAttribute('aria-pressed', 'true');
  });

  it('renders the selected course graph fully laid out', () => {
    render(<KnowledgeGraphDemo />);
    const g = COURSE_GRAPHS[0];
    for (const n of g.nodes) {
      expect(screen.getByTestId(`landing-graph-node-${n.id}`)).toBeInTheDocument();
    }
  });

  it('swaps the graph when another chip is picked', () => {
    render(<KnowledgeGraphDemo />);
    const target = COURSE_GRAPHS[1];
    fireEvent.click(screen.getByTestId(`landing-graph-chip-${target.id}`));

    expect(screen.getByTestId(`landing-graph-node-${target.nodes[0].id}`)).toBeInTheDocument();
    expect(
      screen.queryByTestId(`landing-graph-node-${COURSE_GRAPHS[0].nodes[0].id}`),
    ).not.toBeInTheDocument();
  });

  it('labels the section for assistive tech', () => {
    render(<KnowledgeGraphDemo />);
    expect(screen.getByTestId('landing-graph')).toHaveAttribute('aria-label');
  });
});

describe('KnowledgeGraphDemo — motion', () => {
  it('parks fully assembled when reduced motion is requested', () => {
    // jsdom has no matchMedia; supply one that reports "reduce".
    window.matchMedia = ((q: string) => ({
      matches: q.includes('prefers-reduced-motion'),
      media: q,
      addEventListener() {},
      removeEventListener() {},
    })) as unknown as typeof window.matchMedia;

    render(<KnowledgeGraphDemo />);
    const g = COURSE_GRAPHS[0];

    // Every node present AND at full opacity — parked means complete.
    for (const n of g.nodes) {
      const el = screen.getByTestId(`landing-graph-node-${n.id}`);
      expect(el).toBeInTheDocument();
      expect(el.getAttribute('opacity')).toBe('1');
    }
  });
});

/** Controllable `window.matchMedia`, scoped to the reduced-motion query. */
function installReducedMotion(matches: boolean) {
  const listeners = new Set<() => void>();
  const mql = {
    matches,
    media: '(prefers-reduced-motion: reduce)',
    addEventListener: (_type: string, cb: () => void) => {
      listeners.add(cb);
    },
    removeEventListener: (_type: string, cb: () => void) => {
      listeners.delete(cb);
    },
  };
  window.matchMedia = ((q: string) =>
    q.includes('prefers-reduced-motion')
      ? mql
      : { matches: false, media: q, addEventListener() {}, removeEventListener() {} }) as unknown as typeof window.matchMedia;
  return mql;
}

/**
 * Pins #344 fix round 1: a review finding that reading `window.matchMedia`
 * directly in the component's render body computes a value server-side (no
 * `window`, always "no preference") that can disagree with the real client
 * value, producing a genuine React hydration mismatch for any reduced-motion
 * visitor once this component is mounted with SSR on (a later task does
 * exactly that via `next/dynamic`). `usePrefersReducedMotion` fixes this via
 * `useSyncExternalStore` with a fixed server snapshot, the same pattern
 * `useIsMobile` already uses for the same bug class.
 */
describe('KnowledgeGraphDemo — SSR/hydration parking (#344 fix round 1)', () => {
  let container: HTMLDivElement;
  let root: Root | null = null;
  const actEnv = globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean };

  beforeEach(() => {
    // The file-level `beforeEach` above already cold-starts the reduced-
    // motion store for this test; this block only owns the hydration
    // container + act-environment setup.
    actEnv.IS_REACT_ACT_ENVIRONMENT = true;
    container = document.createElement('div');
    document.body.appendChild(container);
  });

  afterEach(() => {
    if (root) act(() => root!.unmount());
    root = null;
    container.remove();
    actEnv.IS_REACT_ACT_ENVIRONMENT = undefined;
  });

  it('renders the complete frame on the server, and hydrates a reduced-motion client onto it with no recoverable error', async () => {
    const g = COURSE_GRAPHS[0];

    // "SSR-time" world: if a render-body read consulted the live query
    // directly, it would see "no preference" here.
    installReducedMotion(false);
    const html = renderToString(<KnowledgeGraphDemo />);

    const ssrScratch = document.createElement('div');
    ssrScratch.innerHTML = html;
    for (const n of g.nodes) {
      const el = ssrScratch.querySelector(`[data-testid="landing-graph-node-${n.id}"]`);
      expect(el).toBeTruthy();
      // The assertion that pins the fix: SSR output comes from the hook's
      // fixed server snapshot (always "reduced motion" — see its doc
      // comment), not the live query above. A regression to a render-body
      // `window.matchMedia` read would bake progress=0 (mid-assembly,
      // opacity 0) into this string instead of the complete frame.
      expect(el?.getAttribute('opacity')).toBe('1');
    }

    // Now the real client: OS reports reduced motion — deliberately the
    // opposite of the "SSR-time" result above. Using the same value for
    // both phases would let a regression to the old pattern pass this test
    // by accident, since both phases would then just agree by luck.
    __resetReducedMotionStoreForTests();
    installReducedMotion(true);

    container.innerHTML = html;
    const recoverable: unknown[] = [];
    await act(async () => {
      root = hydrateRoot(container, <KnowledgeGraphDemo />, {
        onRecoverableError: (err) => recoverable.push(err),
      });
    });

    // No hydration mismatch, and the reduced-motion client lands on (and
    // stays on) the complete frame — never blank, never mid-assembly.
    expect(recoverable).toEqual([]);
    for (const n of g.nodes) {
      const el = container.querySelector(`[data-testid="landing-graph-node-${n.id}"]`);
      expect(el).toBeTruthy();
      expect(el?.getAttribute('opacity')).toBe('1');
    }
  });
});

describe('KnowledgeGraphDemo — interaction', () => {
  it('shows a concept blurb on hover', () => {
    render(<KnowledgeGraphDemo />);
    const n = COURSE_GRAPHS[0].nodes[1];
    fireEvent.mouseEnter(screen.getByTestId(`landing-graph-node-${n.id}`));
    expect(screen.getByTestId('landing-graph-blurb')).toHaveTextContent(n.blurb);
  });

  it('fades the instructional copy once the visitor interacts', () => {
    render(<KnowledgeGraphDemo />);
    const copy = screen.getByTestId('landing-graph-copy');
    expect(copy).toHaveAttribute('data-engaged', 'false');

    fireEvent.mouseEnter(
      screen.getByTestId(`landing-graph-node-${COURSE_GRAPHS[0].nodes[1].id}`),
    );
    expect(copy).toHaveAttribute('data-engaged', 'true');
  });

  it('keeps the copy faded across a course switch instead of resetting engagement', () => {
    render(<KnowledgeGraphDemo />);
    const copy = screen.getByTestId('landing-graph-copy');

    fireEvent.mouseEnter(
      screen.getByTestId(`landing-graph-node-${COURSE_GRAPHS[0].nodes[1].id}`),
    );
    expect(copy).toHaveAttribute('data-engaged', 'true');

    // `AssemblingGraph` remounts (keyed by `graph.id`) on a course switch.
    // `engaged` lives in the parent specifically so this remount can't wipe
    // it — pin that here, not just at the component-boundary level.
    const target = COURSE_GRAPHS[1];
    fireEvent.click(screen.getByTestId(`landing-graph-chip-${target.id}`));

    expect(copy).toHaveAttribute('data-engaged', 'true');
  });
});

// ── WCAG plumbing for the engaged-copy contrast test (#344 review #2) ───────
// Small enough to inline, and inlining keeps the assertion honest: it derives
// the ratio from the tokens and the opacity the component actually renders,
// rather than restating a number someone computed once by hand.

/** globals.css: `--bg` = `--ink-0`, `--text` = `--ink-800`. */
const TOKEN_BG = '#faf8f3';
const TOKEN_TEXT = '#1a1814';
const TOKEN_BRAND_FOREST = '#1B6C42';

function channels(hex: string): [number, number, number] {
  return [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16)) as [number, number, number];
}

function relativeLuminance([r, g, b]: [number, number, number]): number {
  const lin = (c: number) => {
    const s = c / 255;
    return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
  };
  return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
}

/** WCAG 2.1 contrast of `fg` at `alpha` composited over the opaque `bg`. */
function contrastAtOpacity(fgHex: string, bgHex: string, alpha: number): number {
  const fg = channels(fgHex);
  const bg = channels(bgHex);
  const composited = fg.map((c, i) => alpha * c + (1 - alpha) * bg[i]) as [number, number, number];
  const l1 = relativeLuminance(composited);
  const l2 = relativeLuminance(bg);
  const [hi, lo] = l1 > l2 ? [l1, l2] : [l2, l1];
  return (hi + 0.05) / (lo + 0.05);
}

/**
 * The opacity a visitor actually sees on `el`: CSS opacity composes down the
 * tree, so a fade on the wrapper dims every child and a child can never be
 * *more* opaque than its group. Walking the chain is what makes this test
 * indifferent to *where* the fix put the fade.
 */
function effectiveOpacity(el: Element, stopAt: Element): number {
  let alpha = 1;
  let cur: Element | null = el;
  while (cur) {
    const raw = (cur as HTMLElement).style?.opacity;
    if (raw) alpha *= Number(raw);
    if (cur === stopAt) break;
    cur = cur.parentElement;
  }
  return alpha;
}

/**
 * #344 review #2 — the engaged fade was a flat 0.35 on the whole copy block,
 * and `engaged` never resets, so that was the section's PERMANENT heading
 * treatment for the rest of the session, not a transient animation state.
 * Over this section's flat `--bg` paper that composites the `<h2>` to
 * #ACAAA5 (2.20:1, under the 3:1 large-text bar) and the 0.7rem eyebrow to
 * #ACC7B5 (1.71:1, against a 4.5:1 bar).
 */
describe('KnowledgeGraphDemo — engaged copy contrast (#344 review #2)', () => {
  function engage() {
    render(<KnowledgeGraphDemo />);
    fireEvent.mouseEnter(
      screen.getByTestId(`landing-graph-node-${COURSE_GRAPHS[0].nodes[1].id}`),
    );
    const copy = screen.getByTestId('landing-graph-copy');
    expect(copy).toHaveAttribute('data-engaged', 'true');
    return copy;
  }

  it('keeps the faded headline over the 3:1 WCAG AA bar for large text', () => {
    const copy = engage();
    const headline = copy.querySelector('h2')!;
    const alpha = effectiveOpacity(headline, copy);

    // The headline is text-4xl (36px) semibold — "large text" by WCAG, 3:1.
    // 0.55 composites to #7F7D78 = 3.88:1. The shipped 0.35 was 2.20:1.
    expect(alpha).toBeCloseTo(ENGAGED_HEADLINE_OPACITY, 6);
    expect(contrastAtOpacity(TOKEN_TEXT, TOKEN_BG, alpha)).toBeGreaterThanOrEqual(3);
  });

  it('keeps the small eyebrow over the 4.5:1 WCAG AA bar for small text', () => {
    const copy = engage();
    const eyebrow = copy.querySelector('span')!;
    const alpha = effectiveOpacity(eyebrow, copy);

    // 0.7rem ⇒ small text ⇒ 4.5:1, and `--brand-forest` over the paper only
    // clears that at α ≥ 0.86 — a fade nobody could perceive. So it isn't
    // faded at all: 6.05:1. The shipped 0.35 was 1.71:1.
    expect(contrastAtOpacity(TOKEN_BRAND_FOREST, TOKEN_BG, alpha)).toBeGreaterThanOrEqual(4.5);
  });
});

// ── Controllable IntersectionObserver + rAF, for the gating tests ──────────

type FakeObserverRecord = {
  callback: IntersectionObserverCallback;
  targets: Element[];
  disconnected: boolean;
  rootMargin: string;
};

/** jsdom ships no IntersectionObserver; install one we can fire by hand. */
function installIntersectionObserver() {
  const records: FakeObserverRecord[] = [];

  class FakeIntersectionObserver {
    readonly root = null;
    readonly rootMargin: string;
    readonly thresholds: ReadonlyArray<number> = [0];
    private record: FakeObserverRecord;

    constructor(callback: IntersectionObserverCallback, options?: IntersectionObserverInit) {
      this.rootMargin = String(options?.rootMargin ?? '0px');
      this.record = { callback, targets: [], disconnected: false, rootMargin: this.rootMargin };
      records.push(this.record);
    }
    observe(el: Element) {
      this.record.targets.push(el);
    }
    unobserve(el: Element) {
      this.record.targets = this.record.targets.filter((t) => t !== el);
    }
    disconnect() {
      this.record.disconnected = true;
      this.record.targets = [];
    }
    takeRecords(): IntersectionObserverEntry[] {
      return [];
    }
  }

  const holder = window as unknown as { IntersectionObserver?: unknown };
  const previous = holder.IntersectionObserver;
  holder.IntersectionObserver = FakeIntersectionObserver;

  return {
    records,
    /** Deliver an intersection change to every live observer, inside `act`. */
    fire(isIntersecting: boolean) {
      act(() => {
        for (const r of records) {
          if (r.disconnected) continue;
          r.callback(
            r.targets.map(
              (target) => ({ isIntersecting, target }) as unknown as IntersectionObserverEntry,
            ),
            null as unknown as IntersectionObserver,
          );
        }
      });
    },
    restore() {
      if (previous === undefined) delete holder.IntersectionObserver;
      else holder.IntersectionObserver = previous;
    },
  };
}

/** Capture rAF callbacks instead of letting jsdom schedule them on a timer. */
function captureAnimationFrames() {
  const queue: FrameRequestCallback[] = [];
  const raf = vi
    .spyOn(window, 'requestAnimationFrame')
    .mockImplementation((cb: FrameRequestCallback) => queue.push(cb));
  const caf = vi.spyOn(window, 'cancelAnimationFrame').mockImplementation(() => {});
  return {
    queue,
    get frameCount() {
      return raf.mock.calls.length;
    },
    /** Run the next queued frame inside `act`. */
    step() {
      const cb = queue.shift();
      expect(cb, 'expected a queued animation frame').toBeTruthy();
      act(() => cb!(0));
    },
    restore() {
      raf.mockRestore();
      caf.mockRestore();
    },
  };
}

function nodeOpacities(): string[] {
  return COURSE_GRAPHS[0].nodes.map(
    (n) => screen.getByTestId(`landing-graph-node-${n.id}`).getAttribute('opacity') ?? '',
  );
}

/**
 * #344 review #1 + #6 — two findings that were masking each other.
 *
 * #1: the assembly effect fired on mount, so the helix burned its full 1100ms
 * during the hydration window, underneath the landing page's intro overlay and
 * alongside the hero canvas RAF. Every visitor scrolled down to `progress === 1`
 * and a static picture.
 *
 * #6: the un-park transition (`usePrefersReducedMotion` correcting its SSR-safe
 * `true` to the real `false`) landed `progress` on 0 — a committed frame with
 * the ENTIRE GRAPH at opacity 0. Gating #1 without fixing #6 turns that one
 * blank frame into a section that stays blank until it is scrolled into view,
 * which is exactly what `id="knowledge-graph"` invites someone to deep-link to.
 */
describe('KnowledgeGraphDemo — viewport gating and the never-blank frame (#344 review #1, #6)', () => {
  let observer: ReturnType<typeof installIntersectionObserver>;
  let frames: ReturnType<typeof captureAnimationFrames>;

  beforeEach(() => {
    // The majority visitor: no motion preference, so `parked` is false and the
    // component is on the animated path — the only path where either bug bites.
    installReducedMotion(false);
    observer = installIntersectionObserver();
    frames = captureAnimationFrames();
  });

  afterEach(() => {
    frames.restore();
    observer.restore();
  });

  it('renders the COMPLETE graph, never a blank one, before the section is near the viewport', () => {
    render(<KnowledgeGraphDemo />);
    // Pre-fix this was ["0", "0", "0", ...] — the whole point of #6.
    expect(nodeOpacities()).toEqual(COURSE_GRAPHS[0].nodes.map(() => '1'));
    const edge = screen.getByTestId('landing-graph-svg').querySelector('line')!;
    expect(Number(edge.getAttribute('stroke-opacity'))).toBeGreaterThan(0);
  });

  it('does not start the assembly RAF until the section is reported on screen', () => {
    render(<KnowledgeGraphDemo />);
    // Pre-fix the effect fired on mount and this was already ≥ 1.
    expect(frames.frameCount).toBe(0);
    expect(observer.records).toHaveLength(1);
    expect(observer.records[0].targets).toContain(screen.getByTestId('landing-graph'));
  });

  it('arms the assembly when the section comes into view, and only then', () => {
    render(<KnowledgeGraphDemo />);
    observer.fire(true);
    expect(frames.frameCount).toBeGreaterThan(0);

    frames.step();
    // Now — and only now — a sub-1 frame is legitimate: the visitor is looking
    // at it. The clock has barely moved, so the graph is at the start of the
    // helix.
    expect(nodeOpacities().every((o) => Number(o) < 1)).toBe(true);
  });

  it('settles on the complete frame if the section leaves mid-assembly', () => {
    render(<KnowledgeGraphDemo />);
    observer.fire(true);
    frames.step();
    expect(nodeOpacities().every((o) => Number(o) < 1)).toBe(true);

    // Scrolled away: stop the loop (review #1's "and stop when it leaves"), and
    // don't freeze a half-faded graph behind (review #6).
    observer.fire(false);
    expect(nodeOpacities()).toEqual(COURSE_GRAPHS[0].nodes.map(() => '1'));

    // Coming back doesn't replay the whole helix from blank.
    const before = frames.frameCount;
    observer.fire(true);
    expect(frames.frameCount).toBe(before);
    expect(nodeOpacities()).toEqual(COURSE_GRAPHS[0].nodes.map(() => '1'));
  });

  it('gates on a root margin that cannot already be intersecting at scroll 0', () => {
    render(<KnowledgeGraphDemo />);
    // The section is mounted straight after a `min-h-screen` hero, so its top
    // edge sits at exactly 100vh. A positive bottom rootMargin — the natural
    // "give it some lead-in" reflex — pushes the root's bottom past it and
    // arms the assembly during hydration, which is review #1 all over again.
    const bottomInset = observer.records[0].rootMargin.trim().split(/\s+/)[2] ?? '';
    expect(bottomInset.startsWith('-')).toBe(true);
  });

  it('degrades to the complete frame when the browser has no IntersectionObserver', () => {
    // Deliberate: with no gate available the section stays on its static,
    // fully laid-out frame rather than falling back to an ungated animation.
    // That's the reduced-motion render — correct, crawlable, and never blank.
    observer.restore();
    render(<KnowledgeGraphDemo />);
    expect(nodeOpacities()).toEqual(COURSE_GRAPHS[0].nodes.map(() => '1'));
    expect(frames.frameCount).toBe(0);
  });

  it('disconnects the observer on unmount', () => {
    const { unmount } = render(<KnowledgeGraphDemo />);
    expect(observer.records[0].disconnected).toBe(false);
    unmount();
    expect(observer.records[0].disconnected).toBe(true);
  });
});

/**
 * #344 review #3 — one 900×560 viewBox at every width rendered 4.6 CSS px
 * labels on a 390px phone. `layout.test.ts` owns the arithmetic; this pins that
 * the component actually consults the breakpoint and emits the phone geometry.
 */
describe('KnowledgeGraphDemo — mobile viewBox (#344 review #3)', () => {
  /** Reduced motion (so the frame is parked/complete) at a chosen breakpoint. */
  function installViewport(isMobile: boolean) {
    window.matchMedia = ((q: string) => ({
      matches: q.includes('prefers-reduced-motion') ? true : q.includes('max-width') && isMobile,
      media: q,
      addEventListener() {},
      removeEventListener() {},
    })) as unknown as typeof window.matchMedia;
  }

  it('emits the phone viewBox and label size below the breakpoint', () => {
    installViewport(true);
    render(<KnowledgeGraphDemo />);
    const svg = screen.getByTestId('landing-graph-svg');
    expect(svg.getAttribute('viewBox')).toBe(viewBoxAttr(MOBILE_VIEW.fit));
    expect(svg.querySelector('text')!.getAttribute('font-size')).toBe(String(MOBILE_VIEW.font));
  });

  it('keeps the desktop viewBox above it', () => {
    installViewport(false);
    render(<KnowledgeGraphDemo />);
    const svg = screen.getByTestId('landing-graph-svg');
    expect(svg.getAttribute('viewBox')).toBe(viewBoxAttr(DESKTOP_VIEW.fit));
    expect(svg.querySelector('text')!.getAttribute('font-size')).toBe(String(DESKTOP_VIEW.font));
  });

  /**
   * #344 visual 3 — the frame is DERIVED from the content, never written down.
   * A regression to a hardcoded box is the whole finding, so pin that what the
   * component emits is what `fitViewBox` produced and that it is materially
   * tighter than the layout box it replaced.
   */
  it('renders the fitted frame, not the layout box', () => {
    installViewport(false);
    render(<KnowledgeGraphDemo />);
    const svg = screen.getByTestId('landing-graph-svg');
    expect(svg.getAttribute('viewBox')).not.toBe(`0 0 ${DESKTOP_VIEW.w} ${DESKTOP_VIEW.h}`);
    expect(DESKTOP_VIEW.fit.w).toBeLessThan(DESKTOP_VIEW.w);
    // The fit only pays off with a width cap: stretched across the full
    // container a tighter box would render the graph at 2× and make the
    // section TALLER. Left-aligned + capped is the composition fix (visual 5).
    expect(svg.getAttribute('class')).toContain('md:max-w-[720px]');
  });
});

/**
 * #344 visual 1, 2, 4 — brand conformance and legibility of the drawn nodes.
 */
describe('KnowledgeGraphDemo — node paint and label placement', () => {
  function nodeGroup(id: string) {
    return screen.getByTestId(`landing-graph-node-${id}`);
  }

  it('paints concept nodes with the canonical --state-* tokens', () => {
    render(<KnowledgeGraphDemo />);
    const g = COURSE_GRAPHS[0];
    for (const n of g.nodes) {
      if (n.id === g.rootId) continue;
      const fill = nodeGroup(n.id).querySelector('circle')!.getAttribute('fill');
      expect(fill, n.id).toBe(TIER_COLOR[n.tier]);
      expect(fill, n.id).toMatch(/^var\(--state-/);
    }
  });

  it('paints the course root as the brand anchor, not as a mastery status', () => {
    render(<KnowledgeGraphDemo />);
    const g = COURSE_GRAPHS[0];
    // The fixture tier stays `learning` — this is a render decision, and the
    // amber it used to inherit made the section's focal point read as a warning.
    expect(g.nodes.find((n) => n.id === g.rootId)!.tier).toBe('learning');
    expect(nodeGroup(g.rootId).querySelector('circle')!.getAttribute('fill')).toBe(
      'var(--brand-forest)',
    );
  });

  /**
   * FLIPPED with the upward fan, and the flip is the point rather than a
   * concession. This used to assert the root's label sat ABOVE its circle,
   * which was right while the root sat in the middle of the frame with nothing
   * over it. The root is now the BASE of the drawing and everything grows out
   * of its top, so "above" means "on the stem running up to the middle shoot" —
   * the halo has to cut that edge in two for the course code to stay legible,
   * and the code stops reading as a caption for the whole picture. Below the
   * base there is nothing but frame. Measured, below clears its nearest
   * neighbour by 30.14 units against above's 9.83 (see `labelBaselineY`).
   *
   * The `rootLabelAbove` branch itself is untouched and still covered in
   * `layout.test.ts`; what changed is which side the shipped views ask for.
   */
  it('places every label below its node, the root included', () => {
    render(<KnowledgeGraphDemo />);
    const g = COURSE_GRAPHS[0];

    const rootGroup = nodeGroup(g.rootId);
    const rootCy = Number(rootGroup.querySelector('circle')!.getAttribute('cy'));
    const rootBaseline = Number(rootGroup.querySelector('text')!.getAttribute('y'));
    expect(rootBaseline).toBeGreaterThan(rootCy + DESKTOP_VIEW.rootR);

    const leaf = g.nodes.find((n) => n.id !== g.rootId)!;
    const leafGroup = nodeGroup(leaf.id);
    const leafCy = Number(leafGroup.querySelector('circle')!.getAttribute('cy'));
    const leafBaseline = Number(leafGroup.querySelector('text')!.getAttribute('y'));
    expect(leafBaseline).toBeGreaterThan(leafCy + DESKTOP_VIEW.nodeR);
    // …and the root really is the base: every other node is drawn above it.
    for (const n of g.nodes) {
      if (n.id === g.rootId) continue;
      const cy = Number(nodeGroup(n.id).querySelector('circle')!.getAttribute('cy'));
      expect(cy, `${n.id} should sit above the root`).toBeLessThan(rootCy);
    }
  });

  it('halos label text in the section backdrop so edges break around it', () => {
    render(<KnowledgeGraphDemo />);
    const label = nodeGroup(COURSE_GRAPHS[0].rootId).querySelector('text')!;
    expect(label.getAttribute('stroke')).toBe('var(--bg-mesh)');
    expect(Number(label.getAttribute('stroke-width'))).toBe(DESKTOP_VIEW.labelHalo);
    // Stroke UNDER fill — the other paint order would outline the glyphs.
    expect((label as unknown as SVGTextElement).style.paintOrder).toBe('stroke');
  });
});
