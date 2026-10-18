'use client';

/**
 * Fade a block up into place the first time it is scrolled into view.
 *
 * Replaces the `[data-reveal]` attribute scan that used to live in
 * `useLanding`. Same motion, same threshold; the difference is that a block
 * declares its own entrance where it is written instead of opting into a
 * page-wide `querySelectorAll` that ran on a 900ms interval.
 *
 * The hidden and revealed styles are written straight to the node rather than
 * held in React state. That is not a shortcut — it is what this component
 * actually is. There is no state the rest of the tree can observe, a reveal
 * must land before paint to avoid a flash, and routing it through `useState`
 * means a synchronous set inside a layout effect, i.e. a cascading render on
 * mount for every block on the page. React never writes `opacity` or
 * `transform` here unless a caller puts them in `style`, so the imperative
 * values survive re-renders.
 *
 * Rendering starts visible and is hidden in a layout effect, which runs before
 * paint. Two consequences, both deliberate:
 *
 * - The server-rendered markup is readable. A reader whose JS never arrives
 *   keeps the copy instead of meeting an `opacity:0` section.
 * - There is no flash, because nothing has painted when the hide lands.
 *
 * Two paths never hide at all: reduced motion, and a browser with no
 * IntersectionObserver. Both would otherwise strand real copy at `opacity:0`,
 * which is a far worse failure than an un-animated heading.
 */

import { useLayoutEffect, useRef, type CSSProperties, type ReactNode } from 'react';

import { observeOnce, prefersReducedMotion } from './useInView';

const EASE = 'cubic-bezier(0.22,1,0.36,1)';

/** The subset of tags worth revealing; keeps the ref typing honest. */
type Tag = 'div' | 'section' | 'h1' | 'h2' | 'h3' | 'h4' | 'p' | 'li' | 'span';

export interface FadeInProps {
  /** Element to render. Defaults to a `div`. */
  as?: Tag;
  /** Extra hold before the transition starts, in ms. */
  delay?: number;
  /** How far it travels up, in px. */
  y?: number;
  /** Transition length, in ms. */
  duration?: number;
  className?: string;
  style?: CSSProperties;
  children?: ReactNode;
  /**
   * `data-*` attributes, forwarded verbatim.
   *
   * Not decoration: `DragField` welds its cluster tracks to
   * `[data-drag-anchor]`, and the FAQ column is both an anchor and a reveal.
   * Without passthrough that pairing would have to nest two elements, and the
   * anchor's box is exactly what the field measures.
   */
  [key: `data-${string}`]: unknown;
}

export function FadeIn({
  as: Tag = 'div',
  delay = 0,
  y = 28,
  duration = 800,
  className,
  style,
  children,
  ...rest
}: FadeInProps) {
  const ref = useRef<HTMLElement | null>(null);

  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    // leave it as rendered: visible, un-animated, never observed
    if (prefersReducedMotion() || typeof IntersectionObserver === 'undefined') return;

    el.style.opacity = '0';
    el.style.transform = `translateY(${y}px)`;

    return observeOnce(el, () => {
      el.style.transition = `opacity ${duration}ms ${EASE}, transform ${duration}ms ${EASE}`;
      if (delay) el.style.transitionDelay = `${delay}ms`;
      el.style.opacity = '1';
      el.style.transform = 'none';
    });
  }, [delay, duration, y]);

  return (
    <Tag {...rest} ref={ref as React.Ref<never>} className={className} style={style}>
      {children}
    </Tag>
  );
}
