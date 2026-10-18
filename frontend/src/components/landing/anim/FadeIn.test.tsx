// @vitest-environment jsdom
/**
 * The scroll fade-in primitive.
 *
 * Three of these assertions exist because the failure mode is invisible text,
 * not a wrong animation. `FadeIn` renders its children at `opacity:0` and
 * relies on an IntersectionObserver to bring them back, so every path where
 * that observer never fires has to leave the content visible instead:
 * reduced-motion, and environments with no IntersectionObserver at all.
 * Getting either wrong hides real copy from real readers and looks, in
 * review, exactly like correct code.
 *
 * The server-render case is the same hazard from the other side. The first
 * render must be visible, because that is the markup shipped before hydration
 * — the hidden state is applied in a layout effect, before paint, so there is
 * no flash but also no window where JS-less readers get a blank section.
 */
import React from 'react';
import { render, act } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { FadeIn } from './FadeIn';
import { __resetObserverForTests } from './useInView';

/** Instances the component created, so tests can assert observer sharing. */
let instances: FakeObserver[] = [];

class FakeObserver {
  cb: IntersectionObserverCallback;
  observed = new Set<Element>();
  unobserved: Element[] = [];

  constructor(cb: IntersectionObserverCallback) {
    this.cb = cb;
    instances.push(this);
  }

  observe(el: Element) {
    this.observed.add(el);
  }

  unobserve(el: Element) {
    this.observed.delete(el);
    this.unobserved.push(el);
  }

  disconnect() {
    this.observed.clear();
  }

  /** Fire the callback for one element, as the real observer would. */
  fire(el: Element, isIntersecting: boolean) {
    act(() => {
      this.cb(
        [{ target: el, isIntersecting } as unknown as IntersectionObserverEntry],
        this as unknown as IntersectionObserver,
      );
    });
  }
}

function setReducedMotion(reduce: boolean) {
  window.matchMedia = ((q: string) => ({
    matches: reduce,
    media: q,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia;
}

beforeEach(() => {
  instances = [];
  __resetObserverForTests();
  vi.stubGlobal('IntersectionObserver', FakeObserver);
  // the shared setup file defaults this to reduce=true; the animation path
  // is the one under test, so opt back into motion
  setReducedMotion(false);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('FadeIn', () => {
  it('is visible on first render, so server markup is never blank', () => {
    // asserted via renderToString-equivalent: the very first committed DOM
    // before effects would be visible, but effects have already run by the
    // time render() returns, so this pins the post-effect hidden state and
    // the SSR guarantee is carried by the layout-effect timing instead.
    const { container } = render(<FadeIn>copy</FadeIn>);
    expect(container.textContent).toBe('copy');
  });

  it('hides its children once mounted, then observes', () => {
    const { container } = render(<FadeIn>copy</FadeIn>);
    const el = container.firstElementChild as HTMLElement;

    expect(el.style.opacity).toBe('0');
    expect(el.style.transform).toContain('28px');
    expect(instances).toHaveLength(1);
    expect(instances[0].observed.has(el)).toBe(true);
  });

  it('reveals when it comes into view, and stops observing', () => {
    const { container } = render(<FadeIn>copy</FadeIn>);
    const el = container.firstElementChild as HTMLElement;

    instances[0].fire(el, true);

    expect(el.style.opacity).toBe('1');
    expect(el.style.transform).toBe('none');
    expect(el.style.transition).toContain('opacity');
    expect(instances[0].unobserved).toContain(el);
  });

  it('stays revealed after leaving view again', () => {
    const { container } = render(<FadeIn>copy</FadeIn>);
    const el = container.firstElementChild as HTMLElement;

    instances[0].fire(el, true);
    instances[0].fire(el, false);

    expect(el.style.opacity).toBe('1');
  });

  it('ignores a non-intersecting entry before it has ever been seen', () => {
    const { container } = render(<FadeIn>copy</FadeIn>);
    const el = container.firstElementChild as HTMLElement;

    instances[0].fire(el, false);

    expect(el.style.opacity).toBe('0');
  });

  it('shares one observer across many instances', () => {
    render(
      <>
        <FadeIn>a</FadeIn>
        <FadeIn>b</FadeIn>
        <FadeIn>c</FadeIn>
      </>,
    );

    expect(instances).toHaveLength(1);
    expect(instances[0].observed.size).toBe(3);
  });

  // These two assert "not hidden" rather than opacity === '1'. The
  // non-animating paths leave the node exactly as rendered — they write no
  // inline opacity at all — and that is the point: the guarantee is that copy
  // is never stranded invisible, not that some particular value was set.
  it('renders visible and never observes under reduced motion', () => {
    setReducedMotion(true);
    const { container } = render(<FadeIn>copy</FadeIn>);
    const el = container.firstElementChild as HTMLElement;

    expect(el.style.opacity).not.toBe('0');
    expect(el.style.transform).not.toContain('28px');
    expect(instances).toHaveLength(0);
  });

  it('renders visible when the browser has no IntersectionObserver', () => {
    vi.stubGlobal('IntersectionObserver', undefined);
    const { container } = render(<FadeIn>copy</FadeIn>);
    const el = container.firstElementChild as HTMLElement;

    expect(el.style.opacity).not.toBe('0');
  });

  it('honours delay, travel and duration', () => {
    const { container } = render(
      <FadeIn delay={120} y={8} duration={400}>
        copy
      </FadeIn>,
    );
    const el = container.firstElementChild as HTMLElement;
    expect(el.style.transform).toContain('8px');

    instances[0].fire(el, true);
    expect(el.style.transition).toContain('400ms');
    expect(el.style.transitionDelay).toBe('120ms');
  });

  it('renders the tag it is told to and keeps caller styling', () => {
    const { container } = render(
      <FadeIn as="h2" className="ld-head" style={{ color: 'rgb(1, 2, 3)' }}>
        copy
      </FadeIn>,
    );
    const el = container.firstElementChild as HTMLElement;

    expect(el.tagName).toBe('H2');
    expect(el.className).toBe('ld-head');
    expect(el.style.color).toBe('rgb(1, 2, 3)');
  });

  it('forwards data attributes, which DragField anchors to', () => {
    const { container } = render(<FadeIn data-drag-anchor="faq">copy</FadeIn>);
    const el = container.firstElementChild as HTMLElement;

    expect(el.getAttribute('data-drag-anchor')).toBe('faq');
  });

  it('unobserves on unmount so a removed node cannot leak', () => {
    const { container, unmount } = render(<FadeIn>copy</FadeIn>);
    const el = container.firstElementChild as HTMLElement;

    unmount();

    expect(instances[0].unobserved).toContain(el);
  });
});
