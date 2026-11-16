import { describe, it, expect } from "vitest";
import { flipPlan, offsetBetween, type FlipItem } from "./flipPlan";

const at = (x: number, y: number, parent: string | null = null): FlipItem => ({ box: { x, y, w: 200, h: 40 }, parent });
const layout = (items: Record<string, FlipItem>) => new Map(Object.entries(items));

describe("offsetBetween", () => {
  it("is the translation that draws the new box back at the old place", () => {
    const prev = { x: 220, y: 40, w: 200, h: 40 }, next = { x: 0, y: 92, w: 320, h: 40 };
    expect(offsetBetween(prev, next)).toEqual({ dx: 220, dy: -52 });
    // Applied to the new box it lands on the old one, whatever the sizes.
    expect({ x: next.x + 220, y: next.y - 52 }).toEqual({ x: prev.x, y: prev.y });
    expect(offsetBetween(prev, prev)).toEqual({ dx: 0, dy: 0 });
  });
});

describe("flipPlan", () => {
  it("plans nothing when nothing changed", () => {
    const same = layout({ "col:a": at(0, 0), "tile:1": at(0, 30, "col:a") });
    expect(flipPlan(same, same)).toEqual({ move: [], enter: [], leave: [] });
    expect(flipPlan(new Map(), new Map())).toEqual({ move: [], enter: [], leave: [] });
  });

  it("slides an item that stayed from where it was", () => {
    const prev = layout({ "col:a": at(0, 0), "col:b": at(216, 0), "tile:1": at(0, 30, "col:b"), "tile:2": at(0, 76, "col:b") });
    // Column a went, so b moved left; inside b, tile 1 went and tile 2 moved up.
    const next = layout({ "col:b": at(0, 0), "tile:2": at(0, 30, "col:b") });
    expect(flipPlan(prev, next).move).toEqual([
      { key: "col:b", dx: 216, dy: 0 },
      // Only its move inside the column: the column's slide carries it the rest.
      { key: "tile:2", dx: 0, dy: 46 },
    ]);
  });

  it("does not slide an item that kept its place in a parent that moved", () => {
    const prev = layout({ "col:a": at(0, 0), "col:b": at(216, 0), "tile:1": at(0, 30, "col:b") });
    const next = layout({ "col:b": at(0, 0), "tile:1": at(0, 30, "col:b") });
    expect(flipPlan(prev, next).move.map(m => m.key)).toEqual(["col:b"]);
  });

  it("ignores a move of under a pixel", () => {
    const prev = layout({ "col:a": at(0, 0) });
    expect(flipPlan(prev, layout({ "col:a": at(0.4, -0.6) })).move).toEqual([]);
    expect(flipPlan(prev, layout({ "col:a": at(0, 1) })).move).toEqual([{ key: "col:a", dx: 0, dy: -1 }]);
  });

  it("does not slide an item between two parents", () => {
    const prev = layout({ "col:a": at(0, 0), "col:b": at(216, 0), "tile:1": at(0, 30, "col:a") });
    const next = layout({ "col:a": at(0, 0), "col:b": at(216, 0), "tile:1": at(0, 76, "col:b") });
    expect(flipPlan(prev, next)).toEqual({ move: [], enter: [], leave: [] });
  });

  it("an item that went leaves on its own only when its parent is still there", () => {
    const prev = layout({
      "col:a": at(0, 0), "tile:1": at(0, 30, "col:a"), "tile:2": at(0, 76, "col:a"),
      "col:b": at(216, 0), "tile:3": at(0, 30, "col:b"),
    });
    const next = layout({ "col:a": at(0, 0), "tile:1": at(0, 30, "col:a") });
    // Tile 2 leaves its column; column b leaves whole, with tile 3 inside it.
    expect(flipPlan(prev, next).leave).toEqual(["tile:2", "col:b"]);
  });

  it("an item that came enters on its own only when its parent was already there", () => {
    const prev = layout({ "col:a": at(0, 0), "tile:1": at(0, 30, "col:a") });
    const next = layout({
      "col:a": at(0, 0), "tile:1": at(0, 30, "col:a"), "tile:2": at(0, 76, "col:a"),
      "col:b": at(216, 0), "tile:3": at(0, 30, "col:b"),
    });
    // Tile 2 enters its column; column b enters whole, with tile 3 inside it.
    expect(flipPlan(prev, next)).toEqual({ move: [], enter: ["tile:2", "col:b"], leave: [] });
  });

  it("a change of key at one place is one item going and another coming", () => {
    // How a label is crossfaded: its key carries its text.
    const prev = layout({ band: at(0, 0), "label:Ready for Exam 2": at(90, 4, "band") });
    const next = layout({ band: at(0, 0), "label:Exam 1 coverage": at(90, 4, "band") });
    expect(flipPlan(prev, next)).toEqual({ move: [], enter: ["label:Exam 1 coverage"], leave: ["label:Ready for Exam 2"] });
  });
});
