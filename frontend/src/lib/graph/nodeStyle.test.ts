import { describe, it, expect } from "vitest";
import {
  NODE_STROKE_OPACITY,
  TIER_OPACITY,
  courseLabel,
  edgeWidthFor,
  hexToHsl,
  hslToHex,
  opacityFor,
  radiusFor,
  shadeFor,
  tierFor,
  truncateLabel,
  MASTERY_PALETTE,
  masteryFillFor,
} from "./nodeStyle";

/**
 * A frozen table, not a re-derivation. `shadeFor` is a bit-shift jitter whose
 * only correctness criterion is "the same node keeps the same colour, on every
 * screen, forever" — so the test that protects it has to be literals. A
 * "cleanup" of the shifts that changes any of these is a visible regression on
 * every graph in the app.
 */
const SHADE_GOLDEN = [
  { base: "#7a874f", id: "n1", css: "hsl(91 24% 33%)", hex: "#536840" },
  { base: "#7a874f", id: "recursion", css: "hsl(82 28% 36%)", hex: "#637642" },
  { base: "#3e6f8a", id: "eigenvalues", css: "hsl(209 46% 46%)", hex: "#4077ac" },
  { base: "#7b4b99", id: "base-cases", css: "hsl(297 20% 28%)", hex: "#543956" },
  { base: "#b4562c", id: "subject_root__c1", css: "hsl(43 39% 28%)", hex: "#63532c" },
  { base: "#3f8a7c", id: "a", css: "hsl(190 32% 28%)", hex: "#30575e" },
  { base: "#7a874f", id: "Fundamental theorem of calculus", css: "hsl(61 22% 49%)", hex: "#989961" },
];

describe("shadeFor", () => {
  it.each(SHADE_GOLDEN)("$base + $id → $css / $hex", ({ base, id, css, hex }) => {
    expect(shadeFor(base, id)).toBe(css);
    expect(shadeFor(base, id, "css")).toBe(css);
    expect(shadeFor(base, id, "hex")).toBe(hex);
  });

  it("defaults to the css form the SVG renderers consume", () => {
    expect(shadeFor("#7a874f", "n1")).toMatch(/^hsl\(/);
  });

  it("never returns the space-separated hsl() form in hex mode", () => {
    // Three.js's Color.setStyle rejects `hsl(h s% l%)` and paints BLACK
    for (const { base, id } of SHADE_GOLDEN) {
      expect(shadeFor(base, id, "hex")).toMatch(/^#[0-9a-f]{6}$/);
    }
  });

  it("passes a non-hex base straight through, shading disabled", () => {
    expect(shadeFor("var(--c-sage)", "n1")).toBe("var(--c-sage)");
    expect(shadeFor("var(--c-sage)", "n1", "hex")).toBe("var(--c-sage)");
  });

  it("is stable across calls and independent of the base for the seed", () => {
    expect(shadeFor("#7a874f", "n1")).toBe(shadeFor("#7a874f", "n1"));
    // Different ids on the same course must not collide.
    expect(shadeFor("#7a874f", "n1")).not.toBe(shadeFor("#7a874f", "n2"));
  });
});

describe("hexToHsl / hslToHex", () => {
  it("parses with and without the leading hash, and rejects everything else", () => {
    expect(hexToHsl("#ffffff")).toEqual({ h: 0, s: 0, l: 100 });
    expect(hexToHsl("000000")).toEqual({ h: 0, s: 0, l: 0 });
    expect(hexToHsl("var(--accent)")).toBeNull();
    expect(hexToHsl("#abc")).toBeNull();
  });

  it("round-trips a saturated hue", () => {
    const hsl = hexToHsl("#3e6f8a")!;
    expect(hslToHex(hsl.h, hsl.s, hsl.l)).toBe("#3e6f8a");
  });
});

describe("radiusFor", () => {
  it.each([
    [0, 8],
    [0.25, 11],
    [0.5, 14],
    [1, 20],
  ])("mastery %s → r %s", (mastery, r) => {
    expect(radiusFor(mastery)).toBeCloseTo(r, 10);
  });

  it("pins subject roots at a flat 22 regardless of mastery", () => {
    expect(radiusFor(0, true)).toBe(22);
    expect(radiusFor(1, true)).toBe(22);
  });
});

describe("tierFor", () => {
  // Mirrors backend/config.py::get_mastery_tier — 0.75 / 0.45 / 0.1, boundaries
  // inclusive on the lower end. Pinned so the fifth client-side mirror can't drift.
  it.each([
    [1, "mastered"],
    [0.75, "mastered"],
    [0.7499, "learning"],
    [0.45, "learning"],
    [0.4499, "struggling"],
    [0.1, "struggling"],
    [0.0999, "unexplored"],
    [0, "unexplored"],
  ])("score %s → %s", (score, tier) => {
    expect(tierFor(score)).toBe(tier);
  });
});

describe("opacityFor / TIER_OPACITY", () => {
  it("is the tree's ramp", () => {
    expect(TIER_OPACITY).toEqual({
      mastered: 1,
      learning: 0.78,
      struggling: 0.55,
      unexplored: 0.28,
    });
  });

  it.each(Object.entries(TIER_OPACITY))("tier %s → %s", (tier, op) => {
    expect(opacityFor(tier)).toBe(op);
  });

  it("treats the wire's subject_root as fully opaque", () => {
    expect(opacityFor("subject_root")).toBe(1);
  });

  it("falls back to 0.6 for an unrecognised tier, as the renderer's `|| 0.6` did", () => {
    expect(opacityFor("nonsense")).toBe(0.6);
  });
});

describe("edgeWidthFor", () => {
  // A link is a bar now, not a hairline: 2.2 at its faintest, 5 at its
  // strongest, so it reads as part of the drawing next to a hand-drawn node.
  it.each([
    [0.1, 2.48],
    [0.3, 3.04],
    [0.5, 3.6],
    [0.7, 4.16],
    [1, 5],
  ])("strength %s → %s", (strength, width) => {
    expect(edgeWidthFor(strength)).toBeCloseTo(width, 10);
  });

  it("substitutes 0.5 for a falsy strength, exactly as the renderer's `|| 0.5` did", () => {
    // Including a literal 0 — the quirk is preserved on purpose, because the
    // tree paints a zero-strength edge at the middle width and the golden pins it.
    expect(edgeWidthFor(0)).toBeCloseTo(3.6, 10);
    expect(edgeWidthFor(undefined as unknown as number)).toBeCloseTo(3.6, 10);
  });
});

describe("truncateLabel", () => {
  it("leaves anything up to 18 characters alone", () => {
    expect(truncateLabel("Recursion")).toBe("Recursion");
    expect(truncateLabel("123456789012345678")).toBe("123456789012345678");
  });

  it("cuts to 17 characters plus an ellipsis past 18", () => {
    expect(truncateLabel("1234567890123456789")).toBe("12345678901234567…");
    expect(truncateLabel("Fundamental theorem of calculus")).toBe("Fundamental theor…");
  });

  it("honours a caller-supplied max", () => {
    expect(truncateLabel("Recursion", 5)).toBe("Recu…");
  });
});

describe("courseLabel", () => {
  it("keeps only the course code of a `CODE - Title` name", () => {
    expect(courseLabel("CAS CS 131 - Combinatoric Structures")).toBe("CAS CS 131");
    expect(courseLabel("ENG EK 103 - Computational Linear Algebra")).toBe("ENG EK 103");
  });

  it("leaves a name with no ` - ` separator as it is", () => {
    expect(courseLabel("Biology")).toBe("Biology");
    // A hyphen inside a word is not the separator.
    expect(courseLabel("Self-paced study")).toBe("Self-paced study");
  });

  it("does not cut at a leading separator, which would leave nothing", () => {
    expect(courseLabel(" - Untitled")).toBe(" - Untitled");
  });

  it("cuts a long code or an unsplit name to 22 characters", () => {
    expect(courseLabel("Introduction to Organic Chemistry")).toBe("Introduction to Organ…");
    expect(courseLabel("A very long course code 101 - Title")).toBe("A very long course co…");
  });
});

describe("the mark's constants", () => {
  it("keeps the resting stroke opacity the plain variants use", () => {
    expect(NODE_STROKE_OPACITY).toBe(0.4);
  });
});

describe("masteryFillFor", () => {
  it("maps each server tier to its palette colour and hubs to hub brown", () => {
    expect(masteryFillFor({ mastery_tier: "mastered" })).toBe(MASTERY_PALETTE.mastered);
    expect(masteryFillFor({ mastery_tier: "learning" })).toBe(MASTERY_PALETTE.learning);
    expect(masteryFillFor({ mastery_tier: "struggling" })).toBe(MASTERY_PALETTE.struggling);
    expect(masteryFillFor({ mastery_tier: "unexplored" })).toBe(MASTERY_PALETTE.unexplored);
    expect(masteryFillFor({ is_subject_root: true, mastery_tier: "mastered" })).toBe(MASTERY_PALETTE.hub);
  });

  it("reads an unknown or missing tier as unexplored", () => {
    expect(masteryFillFor({ mastery_tier: "subject_root" })).toBe(MASTERY_PALETTE.unexplored);
    expect(masteryFillFor({ mastery_tier: "toString" })).toBe(MASTERY_PALETTE.unexplored);
    expect(masteryFillFor({ mastery_tier: null })).toBe(MASTERY_PALETTE.unexplored);
    expect(masteryFillFor({})).toBe(MASTERY_PALETTE.unexplored);
  });
});
