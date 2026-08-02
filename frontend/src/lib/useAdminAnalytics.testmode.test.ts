/**
 * NEXT_PUBLIC_TEST_MODE behavior for the analytics range presets.
 *
 * presetRange builds QUERY BOUNDS over `events`/`llm_usage` rows that the
 * backend stamps with its REAL clock — so unlike rendered relative dates
 * (#426), the default must NOT come from testMode's frozen clock. Under the
 * e2e stack the frozen default pointed the dashboard at an empty March 2026
 * window while the journey's events landed in real-clock July, rendering
 * every panel permanently empty (caught by admin-analytics.spec.ts).
 * A #426-family skip-list entry: query bounds stay real.
 *
 * Module-loading strategy mirrors page.testmode.test.tsx: the flag is
 * captured when @/lib/testMode first evaluates, so stub the env at file
 * scope and import lazily.
 */

import { beforeAll, describe, expect, it, vi } from "vitest";

vi.stubEnv("NEXT_PUBLIC_TEST_MODE", "1");

let presetRange: typeof import("./useAdminAnalytics").presetRange;
let TEST_NOW_MS: number;

beforeAll(async () => {
  ({ presetRange } = await import("./useAdminAnalytics"));
  ({ TEST_NOW_MS } = await import("./testMode"));
});

describe("presetRange under NEXT_PUBLIC_TEST_MODE", () => {
  it("defaults to the REAL clock, not the frozen testMode instant", () => {
    const to = Date.parse(presetRange(30).to);
    expect(Math.abs(to - Date.now())).toBeLessThan(60_000);
    expect(Math.abs(to - TEST_NOW_MS)).toBeGreaterThan(86_400_000);
  });
});
