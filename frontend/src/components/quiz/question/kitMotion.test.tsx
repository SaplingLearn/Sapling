// @vitest-environment jsdom
/**
 * kitMotion: the W7 kits' one motion language. A piece glides only while it
 * can still move, a verdict pulses only on a right/wrong tone, nothing that
 * was there on first paint animates in, and reduced motion moves nothing.
 */
import { renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MOTION } from "@/lib/designTokens";

const reduced = vi.hoisted(() => ({ value: false as boolean | null }));

vi.mock("framer-motion", async (importOriginal) => {
  const actual = await importOriginal<typeof import("framer-motion")>();
  return { ...actual, useReducedMotion: () => reduced.value };
});

import { toneOfVerdict, useKitMotion } from "./kitMotion";

afterEach(() => {
  reduced.value = false;
});

describe("toneOfVerdict", () => {
  it("maps a whole-field verdict onto a piece tone", () => {
    expect(toneOfVerdict("correct")).toBe("right");
    expect(toneOfVerdict("incorrect")).toBe("wrong");
    expect(toneOfVerdict(null)).toBe("plain");
    expect(toneOfVerdict(undefined)).toBe("plain");
  });
});

describe("useKitMotion", () => {
  it("never animates a piece in on mount", () => {
    const { result } = renderHook(() => useKitMotion());
    for (const tone of ["plain", "lift", "right", "wrong"] as const) {
      expect(result.current.mark(tone).initial).toBe(false);
      expect(result.current.piece("a", tone, true).initial).toBe(false);
    }
  });

  it("pulses a right piece, shakes a wrong one, and leaves the rest still", () => {
    const { result } = renderHook(() => useKitMotion());
    expect(result.current.mark("plain").animate).toBeUndefined();
    expect(result.current.mark("lift").animate).toBeUndefined();
    expect(result.current.mark("right").animate).toHaveProperty("scale");
    expect(result.current.mark("wrong").animate).toHaveProperty("x");
  });

  it("glides a movable piece on a scoped layoutId, and stops once marked", () => {
    const { result } = renderHook(() => useKitMotion());
    const live = result.current.piece("a", "plain", true);
    expect(live.layout).toBe("position");
    expect(live.layoutId).toMatch(/a$/);
    expect(live.layoutId).not.toBe("a");
    expect(live.transition).toHaveProperty("layout", MOTION.spring.snappy);

    const marked = result.current.piece("a", "right", false);
    expect(marked.layout).toBeUndefined();
    expect(marked.layoutId).toBeUndefined();
  });

  it("scopes layoutIds per mount, so the next question's pieces never fly from the last one's", () => {
    const first = renderHook(() => useKitMotion()).result.current.piece("a", "plain", true).layoutId;
    const second = renderHook(() => useKitMotion()).result.current.piece("a", "plain", true).layoutId;
    expect(first).not.toBe(second);
  });

  it("fades up only what arrives after first paint, one stagger step per step", () => {
    const { result } = renderHook(() => useKitMotion());
    expect(result.current.arrive(false)).toEqual({ initial: false });
    const late = result.current.arrive(true, 1);
    expect(late.initial).toMatchObject({ opacity: 0 });
    expect(late.transition).toHaveProperty("delay", MOTION.stagger.base);
  });

  it("moves nothing under reduced motion", () => {
    reduced.value = true;
    const { result } = renderHook(() => useKitMotion());
    expect(result.current.piece("a", "plain", true).transition).toHaveProperty("layout", { duration: 0 });
    expect(result.current.mark("right").animate).not.toHaveProperty("scale");
    expect(result.current.mark("wrong").animate).not.toHaveProperty("x");
    expect(result.current.arrive(true).initial).not.toHaveProperty("y");
  });
});
