import type { ChartBlock, ChartMarker } from "@/lib/studyGuide/types";

import s from "./blocks.module.css";
import { CHART, chartScale, linePath, shownIn, tickLabel, ticks, type ChartScale, type ChartView } from "./chartModel";

/** One colour per series, in order. */
export const SERIES_COLORS = ["var(--brand-forest)", "var(--info)", "var(--warn)", "var(--c-plum)"];

const { left, right, top, bottom } = CHART;

/** Grid lines and the two axes. The numbers are left off an illustrative chart. */
function Axes({ block, scale }: { block: ChartBlock; scale: ChartScale }) {
  const numbered = !block.illustrative;
  return (
    <>
      {ticks(scale.yDomain, 5).slice(1).map(value => (
        <g key={value}>
          <line x1={left} x2={right} y1={scale.y(value)} y2={scale.y(value)} className={s.chartGrid} />
          {numbered && (
            <text x={left - 8} y={scale.y(value) + 4} textAnchor="end" className={s.chartTick}>
              {tickLabel(value)}
            </text>
          )}
        </g>
      ))}
      {numbered &&
        ticks(scale.xDomain, 3).map(value => (
          <text key={value} x={scale.x(value)} y={bottom + 18} textAnchor="middle" className={s.chartTick}>
            {tickLabel(value)}
          </text>
        ))}
      <line x1={left} x2={right} y1={bottom} y2={bottom} className={s.chartAxis} />
      <line x1={left} x2={left} y1={bottom} y2={top} className={s.chartAxis} />
      <text x={right} y={bottom + 36} textAnchor="end" className={s.chartAxisLabel}>
        {block.x_label}
      </text>
      <text x={left - 8} y={top - 6} textAnchor="end" className={s.chartAxisLabel}>
        {block.y_label}
      </text>
    </>
  );
}

/** A labelled point, with dashed guides down to both axes. */
function Marker({ marker, scale }: { marker: ChartMarker; scale: ChartScale }) {
  const x = scale.x(marker.x);
  const y = scale.y(marker.y);
  const after = marker.state === "after";
  return (
    <g className={after ? s.chartEnter : undefined}>
      <line x1={left} x2={x} y1={y} y2={y} className={s.chartGuide} />
      <line x1={x} x2={x} y1={y} y2={bottom} className={s.chartGuide} />
      <circle cx={x} cy={y} r={7} className={after ? s.chartDotAfter : s.chartDot} />
      <text x={left + 8} y={y - 6} className={s.chartMarkLabel}>
        {marker.y_label}
      </text>
      <text x={x + 6} y={bottom - 8} className={s.chartMarkLabel}>
        {marker.x_label}
      </text>
    </g>
  );
}

/** The chart itself. `alt` is its accessible name: the drawing has no other. */
export function ChartSvg({ block, view }: { block: ChartBlock; view: ChartView }) {
  const scale = chartScale(block);
  return (
    <svg role="img" aria-label={block.alt} viewBox={`0 0 ${CHART.width} ${CHART.height}`} className={s.chart}>
      <Axes block={block} scale={scale} />
      {block.series.map(
        (series, i) =>
          shownIn(series.state, view) && (
            <path
              key={i}
              d={linePath(series.points, scale)}
              stroke={SERIES_COLORS[i % SERIES_COLORS.length]}
              className={series.state === "after" ? `${s.chartLine} ${s.chartLineAfter} ${s.chartEnter}` : s.chartLine}
            />
          ),
      )}
      {block.markers.map((marker, i) => shownIn(marker.state, view) && <Marker key={i} marker={marker} scale={scale} />)}
    </svg>
  );
}
