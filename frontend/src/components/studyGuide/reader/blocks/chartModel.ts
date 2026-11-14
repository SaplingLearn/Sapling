/**
 * The geometry of a chart block: which marks show in each state, and where a
 * data point lands in the drawing. Pure, so the SVG only places things.
 */
import type { ChartBlock, ChartPoint } from "@/lib/studyGuide/types";

export type ChartView = "before" | "after";

/** The drawing's box, in viewBox units. The axes meet at (left, bottom). */
export const CHART = { width: 640, height: 340, left: 70, right: 610, top: 24, bottom: 290 } as const;
/** Data stops short of the top of the y axis, so the axis label has room. */
const PLOT_TOP = 56;

/** The chart has something that only shows After, so it gets the toggle. */
export function chartHasAfter(block: ChartBlock): boolean {
  return block.series.some(series => series.state === "after") || block.markers.some(marker => marker.state === "after");
}

/** A mark made for After is drawn only there. Everything else is always drawn. */
export const shownIn = (state: "both" | "before" | "after", view: ChartView) =>
  state !== "after" || view === "after";

export type Domain = [min: number, max: number];

/** Never zero wide: a flat series still needs a scale. */
function domain(min: number, max: number): Domain {
  return max > min ? [min, max] : [min, min + 1];
}

export interface ChartScale {
  x: (value: number) => number;
  y: (value: number) => number;
  xDomain: Domain;
  yDomain: Domain;
}

/**
 * One scale for both states, so nothing jumps when the toggle flips. The y
 * axis starts at zero unless the data goes below it.
 */
export function chartScale(block: ChartBlock): ChartScale {
  const points: ChartPoint[] = [...block.series.flatMap(series => series.points), ...block.markers];
  const xs = points.map(point => point.x);
  const ys = points.map(point => point.y);
  const xDomain = domain(Math.min(...xs), Math.max(...xs));
  const yDomain = domain(Math.min(0, ...ys), Math.max(...ys));
  return {
    x: value => CHART.left + ((value - xDomain[0]) / (xDomain[1] - xDomain[0])) * (CHART.right - CHART.left),
    y: value => CHART.bottom - ((value - yDomain[0]) / (yDomain[1] - yDomain[0])) * (CHART.bottom - PLOT_TOP),
    xDomain,
    yDomain,
  };
}

/** The series as an SVG path. */
export function linePath(points: ChartPoint[], scale: ChartScale): string {
  return points
    .map((point, i) => `${i === 0 ? "M" : "L"}${scale.x(point.x).toFixed(1)},${scale.y(point.y).toFixed(1)}`)
    .join(" ");
}

/** `count` values spread evenly over the domain, ends included. */
export function ticks([min, max]: Domain, count: number): number[] {
  return Array.from({ length: count }, (_, i) => min + ((max - min) * i) / (count - 1));
}

/**
 * The fewest decimals that write `step` exactly, up to three significant
 * digits of it: enough that ticks a step apart never share a label.
 */
function decimalsFor(step: number): number {
  const most = Math.max(0, 2 - Math.floor(Math.log10(step)));
  for (let decimals = 0; decimals < most; decimals++) {
    const scaled = step * 10 ** decimals;
    if (Math.abs(scaled - Math.round(scaled)) < 1e-6) return decimals;
  }
  return most;
}

/**
 * Evenly spaced ticks as short numbers. Their decimals come from the step
 * between them, so 0.25 reads "0.25", not "0.3", and the ticks of a narrow
 * domain stay apart; trailing zeros are dropped, so a whole tick is whole.
 */
export function tickLabels(values: number[]): string[] {
  const step = values.length > 1 ? Math.abs(values[1] - values[0]) : 0;
  const decimals = step > 0 ? decimalsFor(step) : 0;
  return values.map(value => String(Number(value.toFixed(decimals))));
}
