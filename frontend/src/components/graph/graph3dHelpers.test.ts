// @vitest-environment jsdom
/**
 * Pure-helper tests for the 3D graph's Focused Minimal upgrade.
 * Everything here is deterministic — no three.js, no mocks.
 */
import { describe, it, expect } from "vitest";
import type { GraphNode } from "@/lib/data";
import {
  buildAdjacency,
  hexToRgbTriplet,
  mixHex,
  baseNodeColor,
  labelSpec,
  nodeVal,
  nodeRadius,
  resolveGraphTheme,
  FALLBACK_THEME,
  shadeFor,
} from "./graph3dHelpers";

function makeNode(over: Partial<GraphNode> = {}): GraphNode {
  return {
    id: "n1",
    name: "Node 1",
    subject: "Math",
    color: "#88aa55",
    mastery_tier: "learning",
    mastery_score: 0.5,
    course_id: "c1",
    ...over,
  };
}

describe("buildAdjacency", () => {
  it("maps both directions of every edge", () => {
    const adj = buildAdjacency([{ source: "a", target: "b", strength: 1 }]);
    expect(adj.get("a")?.has("b")).toBe(true);
    expect(adj.get("b")?.has("a")).toBe(true);
    expect(adj.get("c")).toBeUndefined();
  });
});

describe("nodeVal / nodeRadius", () => {
  it("keeps the existing 4..10 mastery scale and 22 for subject roots", () => {
    expect(nodeVal(makeNode({ mastery_score: 0 }))).toBe(4);
    expect(nodeVal(makeNode({ mastery_score: 1 }))).toBe(10);
    expect(nodeVal(makeNode({ is_subject_root: true, mastery_score: 0 }))).toBe(22);
  });
  it("radius follows the library's default sizing (cbrt(val) * 4) so visual scale is unchanged", () => {
    expect(nodeRadius(makeNode({ mastery_score: 0 }))).toBeCloseTo(Math.cbrt(4) * 4);
    expect(nodeRadius(makeNode({ is_subject_root: true }))).toBeCloseTo(Math.cbrt(22) * 4);
  });
});

describe("mixHex", () => {
  it("blends channelwise", () => {
    expect(mixHex("#000000", "#ffffff", 0.5)).toBe("#808080");
    expect(mixHex("#000000", "#ffffff", 0)).toBe("#000000");
    expect(mixHex("#000000", "#ffffff", 1)).toBe("#ffffff");
  });
  it("returns the first color untouched on malformed input", () => {
    expect(mixHex("nope", "#ffffff", 0.5)).toBe("nope");
  });
});

describe("baseNodeColor", () => {
  it("keeps the deterministic per-node shade for explored tiers", () => {
    expect(baseNodeColor(makeNode(), FALLBACK_THEME)).toBe(shadeFor("#88aa55", "n1"));
  });
  it("washes unexplored concept nodes 65% toward the theme dim gray", () => {
    const n = makeNode({ mastery_tier: "unexplored" });
    expect(baseNodeColor(n, FALLBACK_THEME)).toBe(
      mixHex(shadeFor("#88aa55", "n1"), FALLBACK_THEME.dim, 0.65),
    );
  });
  it("never washes subject roots, whatever their tier", () => {
    const n = makeNode({ mastery_tier: "unexplored", is_subject_root: true });
    expect(baseNodeColor(n, FALLBACK_THEME)).toBe(shadeFor("#88aa55", "n1"));
  });
});

describe("labelSpec", () => {
  it("concept labels are small/regular, root labels larger/bold", () => {
    expect(labelSpec(makeNode())).toEqual({ textHeight: 3.2, fontWeight: "400" });
    expect(labelSpec(makeNode({ is_subject_root: true }))).toEqual({
      textHeight: 5,
      fontWeight: "700",
    });
  });
});

describe("resolveGraphTheme", () => {
  it("falls back to the hex constants when CSS vars are absent (jsdom)", () => {
    expect(resolveGraphTheme()).toEqual(FALLBACK_THEME);
  });
});

describe("hexToRgbTriplet", () => {
  it("converts #rrggbb to the comma-separated triplet rgba() needs", () => {
    expect(hexToRgbTriplet("#2d8f5c")).toBe("45, 143, 92");
    expect(hexToRgbTriplet("#000000")).toBe("0, 0, 0");
    expect(hexToRgbTriplet("#ffffff")).toBe("255, 255, 255");
  });
  it("accepts the hash-less form and surrounding whitespace", () => {
    expect(hexToRgbTriplet("8a8372")).toBe("138, 131, 114");
    expect(hexToRgbTriplet("  #8A8372 ")).toBe("138, 131, 114");
  });
  it("falls back to black on anything that is not 6-digit hex", () => {
    // Not a throw: this feeds a CSS string, so an unparseable token must
    // degrade to a visible color rather than emit `rgba(undefined, …)`.
    expect(hexToRgbTriplet("nope")).toBe("0, 0, 0");
    expect(hexToRgbTriplet("#abc")).toBe("0, 0, 0");
    expect(hexToRgbTriplet("rgb(1,2,3)")).toBe("0, 0, 0");
  });
});
