import { describe, it, expect } from "vitest";
import { barHeights } from "./ActivityTab";

describe("barHeights", () => {
  it("scales the tallest bar to the chart height", () => {
    expect(barHeights([50, 100], 100, 140)).toEqual([70, 140]);
  });

  it("gives a zero value a visible stub", () => {
    expect(barHeights([0, 100], 100, 140)).toEqual([4, 140]);
  });

  it("returns stubs when every value is zero", () => {
    expect(barHeights([0, 0, 0], 0, 140)).toEqual([4, 4, 4]);
  });
});
