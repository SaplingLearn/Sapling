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
import r from "./ReadinessBand.module.css";
import s from "./StudyHub.module.css";
import { STATUS_ORDER, TC, squaresOrder, stLabel, type Concept, type Status } from "./studyModel";
import { useCountTo } from "./useCountTo";

function Trend({ points }: { points: number }) {
  if (points === 0) return null;
  const up = points > 0;
  return (
    <span key={points} data-flip={`trend:${points}`} data-flip-how="fade" className={`chip ${up ? "chip--accent" : "chip--err"} ${r.trend}`}>
      {up ? "+" : "−"}{Math.abs(points)}% this week
    </span>
  );
}

function Square({ concept, selected, faded, onToggle }: { concept: Concept; selected: boolean; faded: boolean; onToggle: () => void }) {
  const label = `${concept.name} · ${stLabel(concept.st, concept.ladder)}`;
  return (
    <button className={`${r.square} ${s.hoverSeg}${faded ? ` ${r.squareFaded}` : ""}${selected ? ` ${r.squareSelected}` : ""}`} onClick={onToggle} title={label} aria-label={label} aria-pressed={selected} data-flip={`square:${concept.id}`} data-flip-how="fade"
      style={{ background: TC[concept.st] }} />
  );
}

/** One legend entry, the Dashboard mastery legend's: a round dot, the count, the state. */
function LegendChip({ status, count, on, ladder, onToggle }: { status: Status; count: number; on: boolean; ladder: boolean; onToggle: () => void }) {
  return (
    // Positioned: its count is placed (and crossfaded) inside it.
    <button aria-pressed={on} className={on ? `${r.chip} ${r.chipOn}` : `${r.chip} ${s.hoverLegend}`} onClick={onToggle} title="Highlight these on the roadmap" data-flip={`legend:${status}`}>
      <StatusDot st={status} size={7} />
      <span><span key={count} data-flip={`count:${status}:${count}`} data-flip-how="fade">{count}</span> {stLabel(status, ladder)}</span>
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
function ConceptKey({ concepts, selectedId, level, onSelect, onLevel }: BandProps) {
  return (
    <div className={r.key}>
      {/* A group of buttons, not an image: an image's content is one picture
          to assistive tech, so the squares inside it could not be reached
          (axe nested-interactive). The percentage is the figure above, in text. */}
      <div role="group" aria-label="Concepts" className={r.squares}>
        {squaresOrder(concepts).map(t => (
          <Square key={t.id} concept={t} selected={t.id === selectedId} faded={!!level && t.st !== level}
            onToggle={() => onSelect(t.id === selectedId ? null : t.id)} />
        ))}
      </div>
      <div className={r.legend}>
        {STATUS_ORDER.map(k => (
          <LegendChip key={k} status={k} count={concepts.filter(t => t.st === k).length} on={level === k} ladder={concepts.some(t => t.ladder)}
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
    <div data-flip="band" className={r.band}>
      {/* Centred, not bottom-aligned: the label and trend are a 51px stack
          beside a 72px figure, and sharing a baseline with the digits left
          that stack sitting ~5px below the figure's middle. */}
      <div className={r.figureRow}>
        <span data-testid="readiness-pct" data-flip="pct" className={r.pct}>{measured ? `${pct}%` : "–"}</span>
        <div className={r.labels}>
          <span key={label} data-flip={`label:${label}`} data-flip-how="fade" className={r.label}>{label}</span>
          {measured && props.note && <span key={props.note} data-testid="readiness-unlinked-note" data-flip={`note:${props.note}`} data-flip-how="fade" className={r.note}>{props.note}</span>}
          <Trend points={ready.trend} />
        </div>
      </div>
      {measured && <ConceptKey {...props} />}
    </div>
  );
}
