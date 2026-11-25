// @vitest-environment jsdom
/**
 * lib/motion.ts: every preset is built from MOTION, ends at rest on identity,
 * and under reduced motion moves nothing (opacity only, or instant).
 */
import { renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MOTION } from "./designTokens";

const reduced = vi.hoisted(() => ({ value: false as boolean | null }));

vi.mock("framer-motion", async (importOriginal) => {
  const actual = await importOriginal<typeof import("framer-motion")>();
  return { ...actual, useReducedMotion: () => reduced.value };
});

import { motionPresets, useMotionPresets, type MotionPreset } from "./motion";

/** Properties that move or resize something on screen. */
const MOVEMENT = ["x", "y", "scale", "rotate", "height", "width"];

function moves(target: object): string[] {
  return Object.keys(target).filter((k) => MOVEMENT.includes(k));
}

afterEach(() => {
  reduced.value = false;
});

describe("full motion", () => {
  const m = motionPresets(false);
  const presets: Record<string, MotionPreset> = { fade: m.fade, fadeUp: m.fadeUp, scaleIn: m.scaleIn, collapse: m.collapse };

  it.each(Object.entries(presets))("%s rests on identity", (_name, p) => {
    const rest = p.animate as Record<string, unknown>;
    expect(rest.opacity).toBe(1);
    if ("y" in rest) expect(rest.y).toBe(0);
    if ("scale" in rest) expect(rest.scale).toBe(1);
    if ("height" in rest) expect(rest.height).toBe("auto");
  });

  it("takes its timing from MOTION", () => {
    expect(m.fadeUp.transition).toEqual({ duration: MOTION.duration.base, ease: MOTION.ease.out });
    expect(m.fadeUp.initial).toMatchObject({ y: MOTION.offset.rise });
    expect(m.scaleIn.initial).toMatchObject({ scale: MOTION.offset.scaleFrom });
    expect(m.list.container.shown).toMatchObject({ transition: { staggerChildren: MOTION.stagger.tight } });
  });

  it("pulses a right answer and shakes a wrong one, both back to rest", () => {
    const right = m.pulse("correct").animate.scale as number[];
    const wrong = m.pulse("wrong").animate.x as number[];
    expect(right.at(0)).toBe(1);
    expect(right.at(-1)).toBe(1);
    expect(Math.max(...right)).toBe(MOTION.offset.pulse);
    expect(wrong.at(0)).toBe(0);
    expect(wrong.at(-1)).toBe(0);
  });
});

describe("reduced motion", () => {
  const m = motionPresets(true);

  it.each(["fade", "fadeUp", "scaleIn"] as const)("%s only fades", (name) => {
    const p = m[name];
    expect(moves(p.initial)).toEqual([]);
    expect(moves(p.animate)).toEqual([]);
    expect(moves(p.exit)).toEqual([]);
    expect(p.initial).toMatchObject({ opacity: 0 });
    expect(p.animate).toMatchObject({ opacity: 1 });
  });

  it("snaps a collapse instead of animating its height", () => {
    expect(m.collapse.transition).toEqual({ duration: 0 });
    expect(m.collapse.exit.transition).toEqual({ duration: 0 });
  });

  it("shows a list at once, without movement", () => {
    expect(m.list.container.shown).toEqual({});
    expect(moves(m.list.item.hidden as object)).toEqual([]);
    expect(moves(m.list.item.shown as object)).toEqual([]);
  });

  it("turns the verdict pulse into an opacity blink", () => {
    for (const verdict of ["correct", "wrong"] as const) {
      const p = m.pulse(verdict);
      expect(moves(p.animate)).toEqual([]);
      expect(p.animate.opacity).toEqual([1, MOTION.offset.blink, 1]);
    }
  });

  it("makes every hand-built transition instant", () => {
    for (const t of [m.transition.fast, m.transition.base, m.transition.slow, m.transition.exit, ...Object.values(m.transition.spring)]) {
      expect(t).toEqual({ duration: 0 });
    }
  });
});

describe("useMotionPresets", () => {
  it("follows framer's useReducedMotion", () => {
    reduced.value = true;
    expect(renderHook(() => useMotionPresets()).result.current).toBe(motionPresets(true));
    reduced.value = false;
    expect(renderHook(() => useMotionPresets()).result.current).toBe(motionPresets(false));
  });

  it("treats an unknown preference (null, before framer has read it) as full motion", () => {
    reduced.value = null;
    expect(renderHook(() => useMotionPresets()).result.current).toBe(motionPresets(false));
  });
});
