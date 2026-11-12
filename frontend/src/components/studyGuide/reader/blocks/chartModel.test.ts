/** The chart block's geometry: what shows in each state and where points land. */
import { describe, expect, it } from "vitest";

import type { ChartBlock } from "@/lib/studyGuide/types";

import { CHART, chartHasAfter, chartScale, linePath, shownIn, tickLabel, ticks } from "./chartModel";

const chart = (over: Partial<ChartBlock> = {}): ChartBlock => ({
  type: "chart",
  id: "c1",
  title: "Passes against input size",
  x_label: "Input size",
  y_label: "Passes",
  series: [{ label: "One loop", points: [{ x: 0, y: 0 }, { x: 10, y: 10 }], state: "both" }],
  markers: [],
  readouts: [],
  after_label: "After",
  alt: "A straight line.",
  source_id: null,
  illustrative: true,
  ...over,
});

describe("before and after", () => {
  it("has an After state only when a series or a marker is made for it", () => {
    expect(chartHasAfter(chart())).toBe(false);
    expect(chartHasAfter(chart({ markers: [{ x: 1, y: 1, x_label: "a", y_label: "b", state: "before" }] }))).toBe(false);
    expect(chartHasAfter(chart({ markers: [{ x: 1, y: 1, x_label: "a", y_label: "b", state: "after" }] }))).toBe(true);
    const series = [...chart().series, { label: "Nested", points: [{ x: 0, y: 0 }, { x: 10, y: 100 }], state: "after" as const }];
    expect(chartHasAfter(chart({ series }))).toBe(true);
  });

  it("draws an After mark only in After", () => {
    expect(shownIn("both", "before")).toBe(true);
    expect(shownIn("before", "after")).toBe(true);
    expect(shownIn("after", "before")).toBe(false);
    expect(shownIn("after", "after")).toBe(true);
  });
});

describe("the scale", () => {
  it("puts the domain's corners on the axes", () => {
    const scale = chartScale(chart());
    expect(scale.x(0)).toBe(CHART.left);
    expect(scale.x(10)).toBe(CHART.right);
    expect(scale.y(0)).toBe(CHART.bottom);
    expect(scale.y(10)).toBeLessThan(CHART.bottom);
    expect(scale.y(10)).toBeGreaterThan(CHART.top);
  });

  it("covers both states, so the toggle does not move anything", () => {
    const scale = chartScale(
      chart({ markers: [{ x: 20, y: 400, x_label: "n", y_label: "n squared", state: "after" }] }),
    );
    expect(scale.xDomain).toEqual([0, 20]);
    expect(scale.yDomain).toEqual([0, 400]);
  });

  it("starts the y axis at zero unless the data goes below it", () => {
    const up = chart({ series: [{ label: "a", points: [{ x: 1, y: 5 }, { x: 2, y: 9 }], state: "both" }] });
    expect(chartScale(up).yDomain).toEqual([0, 9]);
    expect(chartScale(up).xDomain).toEqual([1, 2]);
    const down = chart({ series: [{ label: "a", points: [{ x: 1, y: -4 }, { x: 2, y: 9 }], state: "both" }] });
    expect(chartScale(down).yDomain).toEqual([-4, 9]);
  });

  it("still has a scale for a flat series", () => {
    const flat = chart({ series: [{ label: "a", points: [{ x: 3, y: 0 }, { x: 3, y: 0 }], state: "both" }] });
    const scale = chartScale(flat);
    expect(scale.xDomain).toEqual([3, 4]);
    expect(Number.isFinite(scale.x(3))).toBe(true);
    expect(Number.isFinite(scale.y(0))).toBe(true);
  });

  it("writes a series as a path through its points", () => {
    const scale = chartScale(chart());
    expect(linePath(chart().series[0].points, scale)).toBe(
      `M${CHART.left.toFixed(1)},${CHART.bottom.toFixed(1)} L${CHART.right.toFixed(1)},${scale.y(10).toFixed(1)}`,
    );
  });
});

describe("ticks", () => {
  it("spreads them evenly, ends included", () => {
    expect(ticks([0, 100], 5)).toEqual([0, 25, 50, 75, 100]);
    expect(ticks([1, 2], 3)).toEqual([1, 1.5, 2]);
  });

  it("labels whole numbers whole and the rest with one decimal", () => {
    expect(tickLabel(25)).toBe("25");
    expect(tickLabel(1.5)).toBe("1.5");
    expect(tickLabel(0.333)).toBe("0.3");
  });
});
