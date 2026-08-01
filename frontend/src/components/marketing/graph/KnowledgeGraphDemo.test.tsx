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
import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { render, screen, cleanup, fireEvent } from '@testing-library/react';

import KnowledgeGraphDemo from './KnowledgeGraphDemo';
import { COURSE_GRAPHS } from './courseGraphs';
import { __resetReducedMotionStoreForTests } from '@/lib/usePrefersReducedMotion';

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
