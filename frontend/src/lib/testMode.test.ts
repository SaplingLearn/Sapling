/**
 * Unit tests for the NEXT_PUBLIC_TEST_MODE determinism seams (#383).
 *
 * The flag is read at module-evaluation time (NEXT_PUBLIC_ vars are
 * build-time inlined in the app), so each case stubs the env and
 * re-imports the module through a fresh registry.
 */

import { describe, it, expect, vi, afterEach } from "vitest";

type TestModeModule = typeof import("./testMode");

async function load(flag: string): Promise<TestModeModule> {
  vi.resetModules();
  vi.stubEnv("NEXT_PUBLIC_TEST_MODE", flag);
  return import("./testMode");
}

afterEach(() => {
  vi.unstubAllEnvs();
  vi.restoreAllMocks();
  globalThis.__SAPLING_TEST_NOW__ = undefined;
});

describe("mulberry32", () => {
  it("same seed produces the same sequence; different seed diverges", async () => {
    const { mulberry32 } = await load("0");
    const a = mulberry32(42);
    const b = mulberry32(42);
    const seqA = Array.from({ length: 16 }, () => a());
    const seqB = Array.from({ length: 16 }, () => b());
    expect(seqA).toEqual(seqB);
    for (const v of seqA) {
      expect(v).toBeGreaterThanOrEqual(0);
      expect(v).toBeLessThan(1);
    }
    const c = mulberry32(43);
    const seqC = Array.from({ length: 16 }, () => c());
    expect(seqC).not.toEqual(seqA);
  });
});

describe("flag on", () => {
  it("IS_TEST_MODE is true for '1' and 'true'", async () => {
    expect((await load("1")).IS_TEST_MODE).toBe(true);
    expect((await load("true")).IS_TEST_MODE).toBe(true);
  });

  it("random() is seeded: resetTestRng() rewinds to the page-load sequence", async () => {
    const m = await load("1");
    const first = Array.from({ length: 8 }, () => m.random());
    m.resetTestRng();
    const second = Array.from({ length: 8 }, () => m.random());
    expect(second).toEqual(first);
    for (const v of first) {
      expect(v).toBeGreaterThanOrEqual(0);
      expect(v).toBeLessThan(1);
    }
  });

  it("two fresh module loads (≈ two page loads) draw identical sequences", async () => {
    const m1 = await load("1");
    const seq1 = Array.from({ length: 8 }, () => m1.random());
    const m2 = await load("1");
    const seq2 = Array.from({ length: 8 }, () => m2.random());
    expect(seq2).toEqual(seq1);
  });

  it("now() returns the fixed mid-semester weekday-noon instant", async () => {
    const m = await load("1");
    expect(m.now()).toBe(m.TEST_NOW_MS);
    const d = new Date(m.TEST_NOW_MS);
    expect(d.getUTCDay()).toBe(3); // Wednesday
    expect(d.getUTCHours()).toBe(12); // noon UTC
    expect(d.toISOString()).toBe("2026-03-11T12:00:00.000Z");
  });

  it("now() honors an injected clock via globalThis.__SAPLING_TEST_NOW__", async () => {
    const m = await load("1");
    globalThis.__SAPLING_TEST_NOW__ = 1234567890;
    expect(m.now()).toBe(1234567890);
    globalThis.__SAPLING_TEST_NOW__ = undefined;
    expect(m.now()).toBe(m.TEST_NOW_MS);
  });
});

describe("flag off", () => {
  it("IS_TEST_MODE is false for unset-ish values", async () => {
    expect((await load("")).IS_TEST_MODE).toBe(false);
    expect((await load("0")).IS_TEST_MODE).toBe(false);
    expect((await load("false")).IS_TEST_MODE).toBe(false);
  });

  it("random() passes through to Math.random()", async () => {
    const m = await load("0");
    const spy = vi.spyOn(Math, "random").mockReturnValue(0.42);
    expect(m.random()).toBe(0.42);
    expect(spy).toHaveBeenCalledTimes(1);
  });

  it("now() passes through to Date.now() and ignores the injected clock", async () => {
    const m = await load("0");
    const spy = vi.spyOn(Date, "now").mockReturnValue(111222333);
    globalThis.__SAPLING_TEST_NOW__ = 987654321;
    expect(m.now()).toBe(111222333);
    expect(spy).toHaveBeenCalledTimes(1);
  });
});
