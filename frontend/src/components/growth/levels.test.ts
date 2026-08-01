import { describe, it, expect } from "vitest";
import { discFor, RARITY_DISC, stageAssetPath } from "./levels";

describe("discFor", () => {
  it("returns the rarity palette when unlocked", () => {
    expect(discFor("legendary", false)).toEqual(RARITY_DISC.legendary);
  });

  it("returns the grey palette when locked, whatever the rarity", () => {
    expect(discFor("legendary", true)).toEqual(discFor("common", true));
  });

  it("falls back to common for an unknown rarity", () => {
    expect(discFor("mythic" as never, false)).toEqual(RARITY_DISC.common);
  });
});

describe("stageAssetPath", () => {
  it("maps a slug to its committed SVG", () => {
    expect(stageAssetPath("sapling")).toBe("/growth/sapling.svg");
  });
});
