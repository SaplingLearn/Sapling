/**
 * lib/designTokens.ts mirrors globals.css's motion and z-index tokens as
 * numbers. This pins the two together: a value that changes on one side
 * only, or a token that exists on one side only, fails here.
 */
import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { MOTION, Z, cssBezier } from "./designTokens";

const CSS = fs.readFileSync(path.resolve(__dirname, "../app/globals.css"), "utf8");

/** Every custom property declared directly in a top-level `:root { … }` block. */
function rootTokens(css: string): Map<string, string> {
  const text = css.replace(/\/\*[\s\S]*?\*\//g, "");
  const tokens = new Map<string, string>();
  for (const block of text.matchAll(/(?:^|\n):root\s*\{([^{}]*)\}/g)) {
    for (const m of block[1].matchAll(/(--[\w-]+)\s*:\s*([^;]+);/g)) {
      if (!tokens.has(m[1])) tokens.set(m[1], m[2].trim());
    }
  }
  return tokens;
}

const tokens = rootTokens(CSS);

const ms = (value: string): number => {
  const m = /^(\d*\.?\d+)(ms|s)$/.exec(value);
  if (!m) throw new Error(`not a duration: ${value}`);
  return m[2] === "s" ? Number(m[1]) : Number(m[1]) / 1000;
};

const bezier = (value: string): number[] => {
  const m = /^cubic-bezier\(([^)]*)\)$/.exec(value);
  if (!m) throw new Error(`not a cubic-bezier: ${value}`);
  return m[1].split(",").map(Number);
};

const DURATION_TOKEN: Record<keyof typeof MOTION.duration, string> = {
  instant: "--dur-instant",
  fast: "--dur-fast",
  base: "--dur",
  slow: "--dur-slow",
  slower: "--dur-slower",
};

const EASE_TOKEN: Record<keyof typeof MOTION.ease, string> = {
  standard: "--ease",
  out: "--ease-out",
  in: "--ease-in",
  inOut: "--ease-in-out",
  emphasized: "--ease-emphasized",
};

describe("designTokens mirrors globals.css", () => {
  it("finds the :root tokens at all", () => {
    expect(tokens.get("--dur")).toBe("220ms");
  });

  it.each(Object.entries(DURATION_TOKEN))("MOTION.duration.%s = %s", (key, token) => {
    expect(tokens.has(token), `${token} is missing from globals.css`).toBe(true);
    expect(MOTION.duration[key as keyof typeof MOTION.duration]).toBeCloseTo(ms(tokens.get(token)!), 6);
  });

  it.each(Object.entries(EASE_TOKEN))("MOTION.ease.%s = %s", (key, token) => {
    expect(tokens.has(token), `${token} is missing from globals.css`).toBe(true);
    expect([...MOTION.ease[key as keyof typeof MOTION.ease]]).toEqual(bezier(tokens.get(token)!));
  });

  it.each(Object.entries(Z))("Z.%s = --z-%s", (key, value) => {
    const token = `--z-${key}`;
    expect(tokens.has(token), `${token} is missing from globals.css`).toBe(true);
    expect(value).toBe(Number(tokens.get(token)));
  });

  it("has a TS twin for every motion and z-index token in globals.css", () => {
    const mirrored = new Set([
      ...Object.values(DURATION_TOKEN),
      ...Object.values(EASE_TOKEN),
      ...Object.keys(Z).map((k) => `--z-${k}`),
    ]);
    const css = [...tokens.keys()].filter((t) => /^--(dur|ease|z-)/.test(t));
    expect(css.filter((t) => !mirrored.has(t))).toEqual([]);
  });

  it("writes a Bezier back as CSS", () => {
    expect(cssBezier(MOTION.ease.standard)).toBe("cubic-bezier(0.2, 0.7, 0.2, 1)");
  });
});

describe("the spacing scale", () => {
  it("names each step by its size: --sp-N is N × 2px", () => {
    const steps = [...tokens.entries()].filter(([t]) => /^--sp-\d+$/.test(t));
    expect(steps.length).toBeGreaterThan(0);
    for (const [token, value] of steps) {
      expect(value, token).toBe(`${Number(token.slice(5)) * 2}px`);
    }
  });

  it("keeps --pad-* on steps of the scale", () => {
    for (const pad of ["--pad-sm", "--pad-md", "--pad-lg", "--pad-xl"]) {
      const value = tokens.get(pad) ?? "";
      const step = /^var\((--sp-\d+)\)$/.exec(value)?.[1];
      expect(step && tokens.has(step), `${pad}: ${value}`).toBe(true);
    }
  });
});
