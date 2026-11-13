import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, it, expect } from "vitest";
import { HUB_EASE, HUB_EASE_POINTS, HUB_STAGGER_MS, HUB_SWITCH_MS, countAt, cubicBezier, hubEase } from "./hubMotion";

describe("the switch clock", () => {
  it("uses the app's own easing curve", () => {
    const css = readFileSync(path.resolve(__dirname, "../../app/globals.css"), "utf8");
    expect(css).toContain(`--ease: ${HUB_EASE};`);
    expect(HUB_EASE).toBe("cubic-bezier(0.2, 0.7, 0.2, 1)");
  });

  it("keeps the stagger small against the duration", () => {
    expect(HUB_STAGGER_MS).toBeLessThanOrEqual(40);
    expect(HUB_SWITCH_MS).toBeGreaterThanOrEqual(220);
    expect(HUB_SWITCH_MS).toBeLessThanOrEqual(420);
  });
});

describe("cubicBezier", () => {
  it("starts at 0, ends at 1, and holds outside 0..1", () => {
    for (const ease of [hubEase, cubicBezier(0.42, 0, 0.58, 1)]) {
      expect(ease(0)).toBe(0);
      expect(ease(1)).toBe(1);
      expect(ease(-0.5)).toBe(0);
      expect(ease(1.5)).toBe(1);
    }
  });

  it("is the identity for a straight line", () => {
    const linear = cubicBezier(1 / 3, 1 / 3, 2 / 3, 2 / 3);
    for (const t of [0.1, 0.25, 0.5, 0.9]) expect(linear(t)).toBeCloseTo(t, 5);
  });

  it("matches the CSS curve at known points", () => {
    // ease-in-out is symmetric about its middle.
    const inOut = cubicBezier(0.42, 0, 0.58, 1);
    expect(inOut(0.5)).toBeCloseTo(0.5, 5);
    expect(inOut(0.25) + inOut(0.75)).toBeCloseTo(1, 5);
    // CSS `ease`, cubic-bezier(0.25, 0.1, 0.25, 1), is 0.8024 at half time.
    expect(cubicBezier(0.25, 0.1, 0.25, 1)(0.5)).toBeCloseTo(0.8024, 3);
  });

  it("the hub's curve only ever goes forward, fast first", () => {
    expect(HUB_EASE_POINTS).toEqual([0.2, 0.7, 0.2, 1]);
    let before = 0;
    for (let t = 0.05; t <= 1; t += 0.05) {
      const now = hubEase(t);
      expect(now).toBeGreaterThan(before);
      before = now;
    }
    expect(hubEase(0.25)).toBeGreaterThan(0.5); // more than half the way in a quarter of the time
    expect(hubEase(0.5)).toBeGreaterThan(0.8);
  });
});

describe("countAt", () => {
  it("is the old number at the start and exactly the new one from the end on", () => {
    expect(countAt(45, 78, 0)).toBe(45);
    expect(countAt(45, 78, HUB_SWITCH_MS)).toBe(78);
    expect(countAt(45, 78, HUB_SWITCH_MS + 500)).toBe(78);
    expect(countAt(45, 78, -16)).toBe(45); // a frame stamped before the start
  });

  it("is a whole number on the way, never past either end, up or down", () => {
    for (const [from, to] of [[45, 78], [78, 45], [0, 100], [100, 0]]) {
      const lo = Math.min(from, to), hi = Math.max(from, to);
      let last = from;
      for (let ms = 0; ms <= HUB_SWITCH_MS; ms += 16) {
        const n = countAt(from, to, ms);
        expect(Number.isInteger(n)).toBe(true);
        expect(n).toBeGreaterThanOrEqual(lo);
        expect(n).toBeLessThanOrEqual(hi);
        // Never back toward where it came from.
        expect(Math.abs(n - from)).toBeGreaterThanOrEqual(Math.abs(last - from));
        last = n;
      }
    }
  });

  it("follows the hub's curve", () => {
    expect(countAt(0, 100, HUB_SWITCH_MS / 2)).toBe(Math.round(100 * hubEase(0.5)));
    expect(countAt(100, 0, HUB_SWITCH_MS / 4)).toBe(Math.round(100 - 100 * hubEase(0.25)));
  });

  it("does not move when there is nowhere to go", () => {
    expect(countAt(51, 51, 100)).toBe(51);
  });
});
