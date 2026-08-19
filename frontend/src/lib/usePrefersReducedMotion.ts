"use client";

import { useSyncExternalStore } from "react";

const REDUCED_MOTION_QUERY = "(prefers-reduced-motion: reduce)";

type MediaStore = {
  subscribe: (onStoreChange: () => void) => () => void;
  getSnapshot: () => boolean;
};

/**
 * One store for the query, built lazily on first use and reused by every
 * consumer — same rationale as `useIsMobile`'s `stores` map: it keeps
 * `subscribe`'s identity stable across renders so React doesn't tear down
 * and re-establish the `MediaQueryList` listener on every commit.
 */
let cached: MediaStore | null = null;

function store(): MediaStore {
  if (cached) return cached;
  const mql = window.matchMedia(REDUCED_MOTION_QUERY);
  cached = {
    subscribe: (onStoreChange) => {
      mql.addEventListener("change", onStoreChange);
      return () => mql.removeEventListener("change", onStoreChange);
    },
    getSnapshot: () => mql.matches,
  };
  return cached;
}

const noopSubscribe = () => () => {};

/**
 * Server snapshot defaults to `true` (assume reduced motion) — the opposite
 * default from `useIsMobile`'s `false`, and deliberately so. Both hooks
 * resolve the same "server has no window" ambiguity via
 * `useSyncExternalStore`'s `getServerSnapshot`, but the two outcomes aren't
 * symmetric here the way desktop/mobile is:
 *
 *   - Default `true`, real value `false` (a no-preference visitor whose
 *     server guess was "reduced motion"): after hydration commits, the
 *     store's snapshot check corrects to `false` and the entrance animation
 *     plays — one extra replay of an animation for a visitor who by
 *     definition doesn't mind motion. Cosmetic only.
 *   - Default `false`, real value `true` (a reduced-motion visitor whose
 *     server guess was "no preference"): the SSR + hydration paint would
 *     show the graph mid-assembly or blank — exactly what
 *     `prefers-reduced-motion` exists to prevent, for the one population
 *     that asked for it.
 *
 * Given the mismatch is unavoidable for whoever doesn't match the default,
 * default to the direction that's safe to be wrong about: `true`.
 */
const serverSnapshot = () => true;

/**
 * True when the OS/browser reports `prefers-reduced-motion: reduce`. Safe to
 * call during SSR — see `serverSnapshot` above for why it defaults `true`
 * rather than `false`. Reading `window.matchMedia` directly in a render body
 * instead (the bug this hook replaces, #344) computes a fresh value on the
 * server (no `window`, always `false`) and on the first client render (real
 * value), which React then finds disagree — a genuine hydration mismatch
 * on every reduced-motion visitor whenever this component is mounted with
 * SSR on.
 */
export function usePrefersReducedMotion(): boolean {
  const s = typeof window === "undefined" ? null : store();
  return useSyncExternalStore(
    s?.subscribe ?? noopSubscribe,
    s?.getSnapshot ?? serverSnapshot,
    serverSnapshot,
  );
}

/** Test-only: drop the cached `MediaQueryList` store. Not for app code. */
export function __resetReducedMotionStoreForTests() {
  cached = null;
}
