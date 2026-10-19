// @vitest-environment jsdom
/** The shared legend (Home + Learn rail + tutor map) names the four states
 *  with exactly the colours the sapling renderer fills nodes with. */
import React from "react";
import { describe, expect, it } from "vitest";
import { render, screen, within } from "@testing-library/react";

import { SOURCE_GRAPH_PALETTE } from "@/lib/graph/nodeStyle";
import { SaplingMapLegend } from "./SaplingMapLegend";

describe("SaplingMapLegend", () => {
  it("one swatch per state, filled from the renderer's palette, named in text", () => {
    render(<SaplingMapLegend />);
    const list = screen.getByRole("list", { name: "Map key" });
    const items = within(list).getAllByRole("listitem");
    const expected = [
      ["Mastered", SOURCE_GRAPH_PALETTE.mastered],
      ["Learning", SOURCE_GRAPH_PALETTE.learning],
      ["Struggling", SOURCE_GRAPH_PALETTE.struggling],
      ["Unexplored", SOURCE_GRAPH_PALETTE.unexplored],
    ];
    expected.forEach(([label, fill], i) => {
      expect(items[i]).toHaveTextContent(label);
      expect(items[i].querySelector("circle")?.getAttribute("fill")).toBe(fill);
    });
    expect(items[4]).toHaveTextContent("Brown circles are courses");
  });
});
