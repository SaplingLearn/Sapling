/**
 * Day-series helpers shared by the analytics screen and the lazy-loaded
 * chart components. This module deliberately contains NO React/JSX: the
 * screen imports it statically, and a static import pulls its whole module
 * into the eager chunk — keeping it tiny is what lets AnalyticsCharts.tsx
 * stay behind next/dynamic (PR #479 review).
 */

export interface DayPointValue {
  date: string; // YYYY-MM-DD (UTC)
  value: number;
}

const DAY_MS = 86_400_000;
const ZERO_FILL_CAP_DAYS = 400;

/** Zero-fill the sparse server series to one point per UTC day across the
 * range. Ranges longer than the cap return the sparse input unchanged (the
 * line still renders; zero-filling years of days helps nobody). */
export function zeroFillDays(
  points: DayPointValue[],
  fromIso: string,
  toIso: string,
  capDays: number = ZERO_FILL_CAP_DAYS,
): DayPointValue[] {
  const start = Date.parse(fromIso.slice(0, 10) + "T00:00:00.000Z");
  const end = Date.parse(toIso.slice(0, 10) + "T00:00:00.000Z");
  if (!Number.isFinite(start) || !Number.isFinite(end) || end < start) return points;
  const days = Math.round((end - start) / DAY_MS) + 1;
  if (days > capDays) return points;
  const byDate = new Map(points.map((p) => [p.date, p.value]));
  const out: DayPointValue[] = [];
  for (let i = 0; i < days; i++) {
    const date = new Date(start + i * DAY_MS).toISOString().slice(0, 10);
    out.push({ date, value: byDate.get(date) ?? 0 });
  }
  return out;
}

/** Per-day error rate as a PERCENTAGE (0–100): error count ÷ total events,
 * joined by date over the events (denominator) series. Days with zero events
 * report 0 — never NaN/Infinity. Feed both series through zeroFillDays over
 * the SAME range first so the date domains line up. */
export function errorRateSeries(
  errorPoints: DayPointValue[],
  eventPoints: DayPointValue[],
): DayPointValue[] {
  const errByDate = new Map(errorPoints.map((p) => [p.date, p.value]));
  return eventPoints.map((p) => ({
    date: p.date,
    value: p.value > 0 ? ((errByDate.get(p.date) ?? 0) / p.value) * 100 : 0,
  }));
}

/** Compact count for chart axes ("950", "1.5k", "2.5M") — the narrow y-axis
 * gutter can't fit raw token totals; table fallbacks keep the exact values. */
export function formatCompactCount(v: number): string {
  if (v >= 1_000_000) return `${Number((v / 1_000_000).toFixed(1))}M`;
  if (v >= 1_000) return `${Number((v / 1_000).toFixed(1))}k`;
  return String(v);
}
