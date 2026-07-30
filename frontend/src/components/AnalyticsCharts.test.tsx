// @vitest-environment jsdom
/**
 * Chart primitives for the admin analytics dashboard (#122): pure scale/path
 * math plus render contracts for the two hand-rolled SVG forms (day line/area,
 * horizontal category bars). No chart library — these are the tests that keep
 * the math honest.
 */

import React from "react";
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import {
  CategoryBars,
  DayLineChart,
  linePoints,
  niceTicks,
  zeroFillDays,
} from "./AnalyticsCharts";

afterEach(cleanup);

describe("zeroFillDays", () => {
  it("fills every UTC day in the range, zeroing the gaps", () => {
    const out = zeroFillDays(
      [
        { date: "2026-07-10", value: 1 },
        { date: "2026-07-12", value: 3 },
      ],
      "2026-07-09T00:00:00.000Z",
      "2026-07-13T23:59:59.999Z",
    );
    expect(out.map((p) => p.date)).toEqual([
      "2026-07-09", "2026-07-10", "2026-07-11", "2026-07-12", "2026-07-13",
    ]);
    expect(out.map((p) => p.value)).toEqual([0, 1, 0, 3, 0]);
  });

  it("returns the sparse input unchanged when the range exceeds the cap", () => {
    const sparse = [{ date: "2020-01-01", value: 2 }];
    const out = zeroFillDays(sparse, "2020-01-01T00:00:00.000Z", "2026-01-01T00:00:00.000Z");
    expect(out).toEqual(sparse);
  });
});

describe("niceTicks", () => {
  it("produces uniform rounded steps from zero covering the max", () => {
    const ticks = niceTicks(97);
    expect(ticks[0]).toBe(0);
    expect(ticks.at(-1)!).toBeGreaterThanOrEqual(97);
    const step = ticks[1] - ticks[0];
    for (let i = 1; i < ticks.length; i++) expect(ticks[i] - ticks[i - 1]).toBe(step);
  });

  it("handles an all-zero series without collapsing", () => {
    const ticks = niceTicks(0);
    expect(ticks.length).toBeGreaterThanOrEqual(2);
    expect(ticks.at(-1)!).toBeGreaterThan(0);
  });
});

describe("linePoints", () => {
  it("maps values to inverted y (bigger value = smaller y) across the width", () => {
    const pts = linePoints(
      [
        { date: "2026-07-01", value: 0 },
        { date: "2026-07-02", value: 10 },
      ],
      { width: 100, height: 50, max: 10 },
    );
    expect(pts).toHaveLength(2);
    expect(pts[0].x).toBe(0);
    expect(pts[1].x).toBe(100);
    expect(pts[0].y).toBe(50); // value 0 sits on the baseline
    expect(pts[1].y).toBe(0);  // max value sits at the top
  });
});

describe("DayLineChart", () => {
  const series = [
    { date: "2026-07-10", value: 1 },
    { date: "2026-07-11", value: 4 },
    { date: "2026-07-12", value: 2 },
  ];

  it("renders an svg with a line path and an accessible label", () => {
    render(<DayLineChart points={series} color="#1B6C42" ariaLabel="Events per day" />);
    const svg = screen.getByRole("img", { name: "Events per day" });
    expect(svg.querySelector("path[data-part='line']")).toBeTruthy();
  });

  it("renders the empty state when there are no points", () => {
    render(<DayLineChart points={[]} color="#1B6C42" ariaLabel="Events per day" />);
    expect(screen.getByText(/no data/i)).toBeTruthy();
  });
});

describe("CategoryBars", () => {
  it("renders one bar per row with direct value labels", () => {
    const { container } = render(
      <CategoryBars
        rows={[
          { label: "note.created", value: 20 },
          { label: "error.4xx", value: 3 },
        ]}
        ariaLabel="Top event types"
      />,
    );
    expect(container.querySelectorAll("rect[data-part='bar']")).toHaveLength(2);
    expect(screen.getByText("note.created")).toBeTruthy();
    expect(screen.getByText("20")).toBeTruthy();
  });
});
