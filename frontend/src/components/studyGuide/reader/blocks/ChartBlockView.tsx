"use client";
import React from "react";

import { Toggle } from "@/components/ui";
import type { ChartBlock, ChartReadout } from "@/lib/studyGuide/types";

import { useReader } from "../ReaderContext";
import { findSource } from "../readerModel";
import { BlockFrame } from "./BlockFrame";
import s from "./blocks.module.css";
import { chartHasAfter, type ChartView } from "./chartModel";
import { ChartSvg, SERIES_COLORS } from "./ChartSvg";
import { ChartGlyph } from "./glyphs";
import { SourceLine } from "./SourceLine";

/** One number beside the chart: where it starts, or how it moved. */
function Readout({ readout, moved }: { readout: ChartReadout; moved: boolean | null }) {
  return (
    <div className={s.readout}>
      <span className={s.label}>{readout.label}</span>
      <span className={s.readoutValue}>{moved ? `${readout.before} to ${readout.after}` : readout.before}</span>
      {moved !== null && (
        <span className={moved ? s.readoutMoved : s.readoutNote}>{moved ? readout.change : "Starting point"}</span>
      )}
    </div>
  );
}

function Legend({ block }: { block: ChartBlock }) {
  return (
    <ul className={s.legend}>
      {block.series.map((series, i) => (
        <li key={i} style={{ color: SERIES_COLORS[i % SERIES_COLORS.length] }}>
          <span className={series.state === "after" ? s.legendDashed : s.legendLine} aria-hidden="true" />
          {series.label}
        </li>
      ))}
    </ul>
  );
}

export function ChartBlockView({ block }: { block: ChartBlock }) {
  const { guide } = useReader();
  const hasAfter = chartHasAfter(block);
  const [view, setView] = React.useState<ChartView>(hasAfter ? "after" : "before");
  const source = findSource(guide.content.sources, block.source_id);

  const stateToggle = hasAfter && (
    <div role="group" aria-label="Chart state">
      <Toggle<ChartView>
        size="sm"
        testid={`guide-chart-state-${block.id}`}
        options={[
          { value: "before", label: "Before" },
          { value: "after", label: block.after_label },
        ]}
        value={view}
        onChange={setView}
      />
    </div>
  );
  const caption = (source || block.illustrative) && (
    <>
      {source && <SourceLine source={source} />}
      {block.illustrative && <span className={s.illustrative}>Illustrative shape, not plotted from data</span>}
    </>
  );

  return (
    <BlockFrame blockId={block.id} tone="info" icon={<ChartGlyph />} label="Chart" title={block.title} actions={stateToggle} footer={caption}>
      <div className={s.chartBody}>
        <ChartSvg block={block} view={view} />
        <div className={s.chartSide}>
          {block.readouts.map((readout, i) => (
            <Readout key={i} readout={readout} moved={hasAfter ? view === "after" : null} />
          ))}
          <Legend block={block} />
        </div>
      </div>
    </BlockFrame>
  );
}
