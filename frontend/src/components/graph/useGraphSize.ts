"use client";

import React from "react";

export type GraphSize = { w: number; h: number };

/** Re-measures within this (px) are the same size: no re-plan for a rounding. */
const SAME_PX = 1;

/**
 * The element's content box, as the ResizeObserver reports it (inside any
 * border and padding), from its layout size, which a CSS transform (an
 * entrance animation) leaves alone. 0 × 0 when it is not laid out.
 */
function contentSize(el: HTMLElement): GraphSize {
  const cs = window.getComputedStyle(el);
  const px = (v: string) => parseFloat(v) || 0;
  return {
    w: el.clientWidth - px(cs.paddingLeft) - px(cs.paddingRight),
    h: el.clientHeight - px(cs.paddingTop) - px(cs.paddingBottom),
  };
}

/**
 * The size of the element a graph fills, for its `width` and `height`.
 *
 * Returns a callback ref and the size. The ref measures the element the
 * moment it attaches, during the commit, so the update lands before the
 * browser paints, and a ResizeObserver follows it from then on. (A callback
 * ref because the element can mount after the first render — a loading
 * skeleton often comes first — which a plain ref and effect would miss.)
 *
 * The size is `null` until the element attaches: render the graph only once
 * it is known. A graph handed a guessed size lays its courses out for that
 * size, and a frame later, when the real one arrives, visibly re-lays them
 * out. `fallback` stands in where nothing can be measured (an element not
 * laid out yet, or a test DOM); the observer then corrects it.
 */
export function useGraphSize<T extends HTMLElement = HTMLDivElement>(
  fallback: GraphSize,
): [React.RefCallback<T>, GraphSize | null] {
  const [size, setSize] = React.useState<GraphSize | null>(null);
  const observer = React.useRef<ResizeObserver | null>(null);
  // By value, so a fallback written inline doesn't re-attach the ref every render.
  const { w: fallbackW, h: fallbackH } = fallback;

  const ref = React.useCallback((el: T | null) => {
    observer.current?.disconnect();
    observer.current = null;
    if (!el) return;
    const take = (w: number, h: number) =>
      setSize((s) => (s && Math.abs(s.w - w) < SAME_PX && Math.abs(s.h - h) < SAME_PX ? s : { w, h }));
    const now = contentSize(el);
    if (now.w > 0 && now.h > 0) take(now.w, now.h);
    else setSize((s) => s ?? { w: fallbackW, h: fallbackH });
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const { width, height } = entry.contentRect;
        if (width > 0 && height > 0) take(width, height);
      }
    });
    ro.observe(el);
    observer.current = ro;
  }, [fallbackW, fallbackH]);

  return [ref, size];
}
