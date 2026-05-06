import { describe, expect, it } from "vitest";
import { hashSeed, paletteFor } from "./data";

// First entry of COURSE_PALETTE in data.ts. Asserted directly so the
// palette stays internal to data.ts.
const PALETTE_FIRST = "#8a9a5b";

describe("paletteFor", () => {
  it("returns the first palette entry for empty / nullish seeds", () => {
    expect(paletteFor(null)).toBe(PALETTE_FIRST);
    expect(paletteFor(undefined)).toBe(PALETTE_FIRST);
    expect(paletteFor("")).toBe(PALETTE_FIRST);
  });

  it("is deterministic for a given seed", () => {
    expect(paletteFor("course-42")).toBe(paletteFor("course-42"));
  });

  it("produces multiple distinct outputs across varied seeds", () => {
    const colors = new Set(["alpha", "beta", "gamma", "delta"].map(paletteFor));
    expect(colors.size).toBeGreaterThanOrEqual(2);
  });
});

describe("hashSeed", () => {
  it("is deterministic", () => {
    expect(hashSeed("hello")).toBe(hashSeed("hello"));
  });

  it("returns a non-negative integer for typical inputs", () => {
    for (const s of ["", "x", "concept-1", "a longer string with spaces"]) {
      const h = hashSeed(s);
      expect(Number.isInteger(h)).toBe(true);
      expect(h).toBeGreaterThanOrEqual(0);
    }
  });
});
