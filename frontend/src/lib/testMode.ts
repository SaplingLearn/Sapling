/**
 * NEXT_PUBLIC_TEST_MODE determinism seams (#383).
 *
 * Browser-test (Playwright) builds set NEXT_PUBLIC_TEST_MODE=1 so the
 * DOM becomes deterministic: seeded PRNG instead of Math.random(), a
 * frozen clock instead of Date.now(), rAF loops parked, framer-motion
 * animations skipped, and force-graph cooldowns zeroed.
 *
 * NEXT_PUBLIC_ vars are inlined at build time, so with the flag off
 * every test-mode branch below is statically false — production
 * bundles keep the exact Math.random()/Date.now() behavior.
 */

export const IS_TEST_MODE =
  process.env.NEXT_PUBLIC_TEST_MODE === "1" ||
  process.env.NEXT_PUBLIC_TEST_MODE === "true";

/**
 * mulberry32 — tiny 32-bit seeded PRNG. Same seed ⇒ same sequence,
 * values in [0, 1) like Math.random().
 */
export function mulberry32(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), a | 1);
    t = (t + Math.imul(t ^ (t >>> 7), t | 61)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const TEST_SEED = 0x5eed_383; // arbitrary but fixed (383 = the issue)

let testRng = mulberry32(TEST_SEED);

/**
 * Drop-in Math.random() replacement. Seeded + deterministic when the
 * flag is on; passthrough to Math.random() otherwise. The sequence
 * restarts on every page load (module init), so two consecutive loads
 * of the same view draw identical values.
 */
export function random(): number {
  return IS_TEST_MODE ? testRng() : Math.random();
}

/**
 * Rewind the seeded sequence to its page-load state. Only meaningful
 * in test mode; unit tests use it to simulate a fresh page load
 * without tearing down the module registry.
 */
export function resetTestRng(): void {
  testRng = mulberry32(TEST_SEED);
}

/**
 * The frozen test-mode instant: Wednesday 2026-03-11T12:00:00Z — a
 * mid-semester weekday noon. Local-time renderings of it (greeting,
 * calendar "today") are stable as long as the browser test pins its
 * timezone (Playwright: `timezoneId`).
 */
export const TEST_NOW_MS = Date.UTC(2026, 2, 11, 12, 0, 0);

declare global {
  var __SAPLING_TEST_NOW__: number | undefined;
}

/**
 * Drop-in Date.now() replacement. In test mode returns TEST_NOW_MS,
 * unless the harness injects a clock by setting
 * `globalThis.__SAPLING_TEST_NOW__` (e.g. via Playwright addInitScript)
 * to pick a different frozen instant per scenario.
 */
export function now(): number {
  if (!IS_TEST_MODE) return Date.now();
  const injected = globalThis.__SAPLING_TEST_NOW__;
  return typeof injected === "number" ? injected : TEST_NOW_MS;
}
