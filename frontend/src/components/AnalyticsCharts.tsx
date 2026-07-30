"use client";

/**
 * Hand-rolled SVG chart primitives for the admin analytics dashboard (#122).
 * No chart library (bundle discipline) — two forms cover every panel:
 *
 *   - DayLineChart: single-series change-over-time (events/day, cost/day,
 *     errors/day). 2px line + soft area fill, recessive grid, crosshair +
 *     tooltip hover layer, ≥8px hover marker.
 *   - CategoryBars: magnitude across a short category list (top event types,
 *     cost by group). Thin horizontal bars, one hue, 4px rounded DATA end
 *     (baseline end stays square), direct value labels.
 *
 * Color notes (dataviz skill, validated via validate_palette.js): every chart
 * here is single-series, so hues encode panel identity, not categories — the
 * forest green (#1B6C42) and the status red (--err) never share a plot, and
 * the errors panel carries its title + labels so identity is never
 * color-alone. Text always wears text tokens, never the series color.
 */

import React from "react";
import { type DayPointValue, zeroFillDays } from "@/lib/daySeries";

// Re-exported so chart consumers/tests can keep a single import site; the
// canonical home is lib/daySeries.ts (JSX-free — see its header for why).
export { zeroFillDays, type DayPointValue };

/** Uniform "nice"-stepped ticks from 0 covering max (used for the y grid). */
export function niceTicks(max: number, count = 4): number[] {
  const target = max > 0 ? max : 1;
  const rawStep = target / count;
  const mag = 10 ** Math.floor(Math.log10(rawStep));
  const nice = [1, 2, 2.5, 5, 10].find((m) => m * mag >= rawStep) ?? 10;
  const step = nice * mag;
  const ticks: number[] = [];
  for (let v = 0; v < target + step; v += step) ticks.push(Number(v.toFixed(6)));
  return ticks;
}

/** Tooltip x-position as a PERCENTAGE of the chart wrapper. The tooltip is
 * an HTML sibling of a scaled SVG (viewBox width ≠ rendered CSS width when
 * the container is narrower than the measurement floor), so viewBox pixels
 * would drift; a wrapper percentage tracks the rendered scale exactly.
 * Clamped to 8–92% so the box never clips the panel edges. */
export function tooltipLeftPct(x: number, padL: number, width: number): number {
  const pct = ((x + padL) / Math.max(width, 1)) * 100;
  return Math.round(Math.min(Math.max(pct, 8), 92) * 100) / 100;
}

/** Map day points onto plot coordinates; y is inverted (SVG grows downward). */
export function linePoints(
  points: DayPointValue[],
  plot: { width: number; height: number; max: number },
): { x: number; y: number; point: DayPointValue }[] {
  const { width, height, max } = plot;
  const denom = Math.max(points.length - 1, 1);
  const safeMax = max > 0 ? max : 1;
  return points.map((point, i) => ({
    x: points.length === 1 ? width / 2 : (i / denom) * width,
    y: height - (point.value / safeMax) * height,
    point,
  }));
}

/** Container-width measurement; falls back to the default width when
 * ResizeObserver is unavailable (jsdom). */
function useMeasuredWidth(fallback: number): [React.RefObject<HTMLDivElement | null>, number] {
  const ref = React.useRef<HTMLDivElement | null>(null);
  const [width, setWidth] = React.useState(fallback);
  React.useEffect(() => {
    if (typeof ResizeObserver === "undefined" || !ref.current) return;
    const ro = new ResizeObserver((entries) => {
      const w = entries[0]?.contentRect.width;
      if (w) setWidth(Math.max(240, Math.floor(w)));
    });
    ro.observe(ref.current);
    return () => ro.disconnect();
  }, []);
  return [ref, width];
}

function EmptyNote() {
  return <div style={{ color: "var(--text-muted)", fontSize: 13 }}>No data in this range.</div>;
}

const AXIS_TEXT: React.CSSProperties = {
  fontSize: 10,
  fill: "var(--text-muted)",
  fontVariantNumeric: "tabular-nums",
};

export function DayLineChart({
  points,
  color,
  fillColor,
  ariaLabel,
  format = (v: number) => String(v),
  height = 150,
}: {
  points: DayPointValue[];
  color: string;
  fillColor?: string;
  ariaLabel: string;
  format?: (v: number) => string;
  height?: number;
}) {
  const [wrapRef, width] = useMeasuredWidth(600);
  const [hover, setHover] = React.useState<number | null>(null);
  if (points.length === 0) return <EmptyNote />;

  const PAD_L = 36;
  const PAD_B = 18;
  const PAD_T = 8;
  const plotW = Math.max(width - PAD_L - 8, 40);
  const plotH = height - PAD_T - PAD_B;
  const max = Math.max(...points.map((p) => p.value));
  const ticks = niceTicks(max);
  const top = ticks.at(-1)!;
  const pts = linePoints(points, { width: plotW, height: plotH, max: top });
  const line = pts.map((p, i) => `${i === 0 ? "M" : "L"}${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(" ");
  const area = `${line} L${pts.at(-1)!.x.toFixed(1)},${plotH} L${pts[0].x.toFixed(1)},${plotH} Z`;
  const hovered = hover != null ? pts[hover] : null;

  const onMove = (e: React.PointerEvent<SVGRectElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const x = ((e.clientX - rect.left) / rect.width) * plotW;
    let best = 0;
    for (let i = 1; i < pts.length; i++) if (Math.abs(pts[i].x - x) < Math.abs(pts[best].x - x)) best = i;
    setHover(best);
  };

  return (
    <div ref={wrapRef} style={{ position: "relative" }}>
      <svg role="img" aria-label={ariaLabel} width="100%" height={height} viewBox={`0 0 ${width} ${height}`}>
        <g transform={`translate(${PAD_L},${PAD_T})`}>
          {ticks.map((t) => {
            const y = plotH - (t / top) * plotH;
            return (
              <g key={t}>
                <line x1={0} x2={plotW} y1={y} y2={y} stroke="var(--border)" strokeWidth={1} />
                <text x={-6} y={y + 3} textAnchor="end" style={AXIS_TEXT}>{format(t)}</text>
              </g>
            );
          })}
          {fillColor && <path d={area} fill={fillColor} opacity={0.6} />}
          <path d={line} data-part="line" fill="none" stroke={color} strokeWidth={2} strokeLinejoin="round" />
          {hovered && (
            <>
              <line x1={hovered.x} x2={hovered.x} y1={0} y2={plotH} stroke="var(--text-muted)" strokeWidth={1} strokeDasharray="3 3" />
              <circle cx={hovered.x} cy={hovered.y} r={4.5} fill={color} stroke="var(--bg-panel)" strokeWidth={2} />
            </>
          )}
          <text x={0} y={plotH + 13} style={AXIS_TEXT}>{points[0].date}</text>
          <text x={plotW} y={plotH + 13} textAnchor="end" style={AXIS_TEXT}>{points.at(-1)!.date}</text>
          <rect
            x={0} y={0} width={plotW} height={plotH} fill="transparent"
            onPointerMove={onMove} onPointerLeave={() => setHover(null)}
          />
        </g>
      </svg>
      {hovered && (
        <div
          role="status"
          style={{
            position: "absolute",
            left: `${tooltipLeftPct(hovered.x, PAD_L, width)}%`,
            transform: "translateX(-50%)",
            top: 0,
            background: "var(--bg-panel)",
            border: "1px solid var(--border)",
            borderRadius: "var(--r-sm)",
            boxShadow: "var(--shadow-sm)",
            padding: "4px 8px",
            fontSize: 12,
            pointerEvents: "none",
            whiteSpace: "nowrap",
          }}
        >
          <span style={{ color: "var(--text-muted)" }}>{hovered.point.date}</span>{" "}
          <strong style={{ fontVariantNumeric: "tabular-nums" }}>{format(hovered.point.value)}</strong>
        </div>
      )}
    </div>
  );
}

/** Horizontal bar with the DATA end rounded (4px) and the baseline end square. */
function barPath(w: number, h: number): string {
  const r = Math.min(4, w, h / 2);
  return `M0,0 H${w - r} A${r},${r} 0 0 1 ${w},${r} V${h - r} A${r},${r} 0 0 1 ${w - r},${h} H0 Z`;
}

export function CategoryBars({
  rows,
  ariaLabel,
  color = "var(--brand-forest, #1B6C42)",
  format = (v: number) => String(v),
}: {
  rows: { label: string; value: number }[];
  ariaLabel: string;
  color?: string;
  format?: (v: number) => string;
}) {
  if (rows.length === 0) return <EmptyNote />;
  const max = Math.max(...rows.map((r) => r.value), 1);
  return (
    <div role="img" aria-label={ariaLabel} style={{ display: "grid", gap: 6 }}>
      {rows.map((row) => {
        const pct = Math.max((row.value / max) * 100, 0.5);
        return (
          <div
            key={row.label}
            style={{
              display: "grid",
              gridTemplateColumns: "minmax(120px, 220px) 1fr 64px",
              alignItems: "center",
              gap: 8,
            }}
          >
            <span style={{ fontSize: 12, color: "var(--text-dim)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              {row.label}
            </span>
            <svg width={`${pct}%`} height={14} viewBox="0 0 100 14" preserveAspectRatio="none" style={{ minWidth: 3 }}>
              <path d={barPath(100, 14)} data-part="bar-shape" fill={color} />
              <rect data-part="bar" x={0} y={0} width={100} height={14} fill="transparent">
                <title>{`${row.label}: ${format(row.value)}`}</title>
              </rect>
            </svg>
            <span style={{ fontSize: 12, textAlign: "right", fontVariantNumeric: "tabular-nums" }}>
              {format(row.value)}
            </span>
          </div>
        );
      })}
    </div>
  );
}
