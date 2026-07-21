"use client";

import { useSyncExternalStore } from "react";

export const MOBILE_BREAKPOINT = 768;

type MediaStore = {
  subscribe: (onStoreChange: () => void) => () => void;
  getSnapshot: () => boolean;
};

/**
 * One store per breakpoint, so every consumer of the same breakpoint shares a
 * single `MediaQueryList` and a single listener instead of one per component.
 * `subscribe` must also be referentially stable across renders — a fresh
 * closure would make React tear down and re-establish the subscription on
 * every render.
 */
const stores = new Map<number, MediaStore>();

function storeFor(breakpoint: number): MediaStore {
  const cached = stores.get(breakpoint);
  if (cached) return cached;

  const mql = window.matchMedia(`(max-width: ${breakpoint - 1}px)`);
  const store: MediaStore = {
    subscribe: (onStoreChange) => {
      mql.addEventListener("change", onStoreChange);
      return () => mql.removeEventListener("change", onStoreChange);
    },
    getSnapshot: () => mql.matches,
  };
  stores.set(breakpoint, store);
  return store;
}

const serverSnapshot = () => false;
const noopSubscribe = () => () => {};

/**
 * True below `breakpoint`. Safe to call during SSR.
 *
 * The server has no viewport, so `getServerSnapshot` reports "desktop" — and
 * React reuses that same value for the hydrating render, which is what keeps
 * server and first client render in agreement. Reading `matchMedia` up front
 * instead would produce a hydration mismatch on every phone.
 *
 * That means this hook can never make the *pre-hydration* paint correct; it
 * only corrects the tree once React commits. Anything that must look right in
 * that first frame belongs in a CSS `@media` rule (see globals.css), not here.
 */
export function useIsMobile(breakpoint: number = MOBILE_BREAKPOINT): boolean {
  const store = typeof window === "undefined" ? null : storeFor(breakpoint);
  return useSyncExternalStore(
    store?.subscribe ?? noopSubscribe,
    store?.getSnapshot ?? serverSnapshot,
    serverSnapshot,
  );
}

/** Test-only: drop the cached `MediaQueryList` stores. Not for app code. */
export function __resetMediaStoresForTests() {
  stores.clear();
}
