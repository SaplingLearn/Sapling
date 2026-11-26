"use client";
/**
 * The readiness figure: the percentage, what it speaks for, this week's trend,
 * a square per concept and the legend that filters the roadmap by status.
 *
 * It follows the selected exam: the figure, trend, squares and legend counts
 * are over the concepts the outline puts on that exam, or over the whole
 * course (labelled as the course, with a note that the exam has nothing
 * linked) when it puts none.
 *
 * A change of exam does not replace the band: each part goes from its old
 * value to its new one, with the rest of the hub (./hubMotion.ts). The figure
 * counts; the `data-flip` parts are moved and crossfaded by the hub's useFlip
 * (a key that carries the text means "crossfade when the text changes", and
 * is the element's React key too, as useFlip asks).
 */
import React from "react";
import { StatusDot } from "./hubUi";
import s from "./StudyHub.module.css";
import { ST_LABEL, STATUS_ORDER, TC, squaresOrder, type Concept, type Status } from "./studyModel";
import { useCountTo } from "./useCountTo";
import { cn } from "@/lib/cn";

function Trend({ points }: { points: number }) {
  if (points === 0) return null;
  const up = points > 0;
  return (
    <span key={points} className={cn(`chip ${up ? "chip--accent" : "chip--err"}`, "self-start")} data-flip={`trend:${points}`} data-flip-how="fade">
      {up ? "+" : "−"}{Math.abs(points)}% this week
    </span>
  );
}

function Square({ concept, selected, faded, onToggle }: { concept: Concept; selected: boolean; faded: boolean; onToggle: () => void }) {
  const label = `${concept.name} · ${ST_LABEL[concept.st]}`;
  return (
    <button className={cn(s.hoverSeg, "w-3.5 h-3.5 shrink-0 p-0 border-0 rounded-xs cursor-pointer", faded ? "opacity-30" : "opacity-100", selected ? "[box-shadow:0_0_0_1.5px_var(--bg),_0_0_0_3px_var(--brand-forest)]" : "shadow-none")} onClick={onToggle} title={label} aria-label={label} data-flip={`square:${concept.id}`} data-flip-how="fade"
      style={{ background: TC[concept.st] }} />
  );
}

/** One legend entry, the Dashboard mastery legend's: a round dot, the count, the state. */
function LegendChip({ status, count, on, onToggle }: { status: Status; count: number; on: boolean; onToggle: () => void }) {
  return (
    // Positioned: its count is placed (and crossfaded) inside it.
    <button aria-pressed={on} className={cn(on ? undefined : s.hoverLegend, "relative inline-flex items-center gap-[5px] h-5.5 pt-0 pr-2 pb-0 pl-1.5 border-0 rounded-[var(--r-full)] [font-family:inherit] [font-weight:inherit] [font-style:inherit] [line-height:inherit] text-xs cursor-pointer", on ? "[background:var(--sap-100)]" : "[background:transparent]", on ? "text-text" : "text-text-muted")} onClick={onToggle} title="Highlight these on the roadmap" data-flip={`legend:${status}`}>
      <StatusDot st={status} size={7} />
      <span><span key={count} data-flip={`count:${status}:${count}`} data-flip-how="fade">{count}</span> {ST_LABEL[status]}</span>
    </button>
  );
}

type BandProps = {
  /** "Ready for <exam>" ("<exam> coverage" once it is past), or the course's name when the figure is the course's. */
  label: string;
  /** Says the selected exam has nothing linked, when the figure is the course's for that reason. */
  note: string | null;
  /** The concepts the figure is over. With none there is nothing to measure,
   *  and the band says so ("–") rather than "0%", which reads as a score. */
  concepts: Concept[];
  /** Mean mastery, and the percentage points gained (or lost) this week. */
  ready: { pct: number; trend: number };
  /** The clicked concept, if any. */
  selectedId: string | null;
  /** The legend's status filter. */
  level: Status | null;
  onSelect: (conceptId: string | null) => void;
  onLevel: (level: Status | null) => void;
};

/** A square per concept, and the legend that filters the roadmap by status. */
function ConceptKey({ concepts, ready, selectedId, level, onSelect, onLevel }: BandProps) {
  return (
    <div className="flex flex-col gap-2.5">
      <div role="img" aria-label={`Overall mastery ${ready.pct} percent`} className="flex flex-wrap gap-1">
        {squaresOrder(concepts).map(t => (
          <Square key={t.id} concept={t} selected={t.id === selectedId} faded={!!level && t.st !== level}
            onToggle={() => onSelect(t.id === selectedId ? null : t.id)} />
        ))}
      </div>
      <div className="flex flex-wrap gap-y-0.5 gap-x-1 -ml-1.5">
        {STATUS_ORDER.map(k => (
          <LegendChip key={k} status={k} count={concepts.filter(t => t.st === k).length} on={level === k}
            onToggle={() => onLevel(level === k ? null : k)} />
        ))}
      </div>
    </div>
  );
}

export function ReadinessBand(props: BandProps) {
  const { label, ready } = props;
  // With no concepts there is nothing to draw or filter; the block beside it says why.
  const measured = props.concepts.length > 0;
  const pct = useCountTo(ready.pct);
  return (
    // Centred against the Up Next block beside it. Nothing here changes height
    // with the selected concept, so centring never makes the figure jump. A
    // concept's missing prerequisite is marked on its roadmap tile.
    <div data-flip="band" className="relative self-stretch flex flex-col justify-center gap-3.5 min-w-0">
      {/* Centred, not bottom-aligned: the label and trend are a 51px stack
          beside a 72px figure, and sharing a baseline with the digits left
          that stack sitting ~5px below the figure's middle. */}
      <div className="flex items-center gap-3.5">
        <span data-testid="readiness-pct" data-flip="pct" className="font-display text-[72px] font-semibold leading-none tracking-[-0.02em]">{measured ? `${pct}%` : "–"}</span>
        <div className="flex flex-col gap-[3px]">
          <span key={label} data-flip={`label:${label}`} data-flip-how="fade" className="text-base leading-[1.3] font-semibold">{label}</span>
          {measured && props.note && <span key={props.note} data-testid="readiness-unlinked-note" data-flip={`note:${props.note}`} data-flip-how="fade" className="text-sm leading-[1.3] text-text-muted">{props.note}</span>}
          <Trend points={ready.trend} />
        </div>
      </div>
      {measured && <ConceptKey {...props} />}
    </div>
  );
}
