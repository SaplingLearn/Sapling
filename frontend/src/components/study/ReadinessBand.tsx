"use client";
/**
 * The readiness figure: the percentage, what it speaks for, this week's trend,
 * a square per concept and the legend that filters the roadmap by status.
 *
 * It follows the selected exam: the figure, trend, squares and legend counts
 * are over the concepts the outline puts on that exam, or over the whole
 * course (labelled as the course) when it puts none.
 */
import React from "react";
import { INHERIT_FONT } from "@/lib/inheritFont";
import { DISPLAY, StatusDot } from "./hubUi";
import s from "./StudyHub.module.css";
import { ST_LABEL, STATUS_ORDER, TC, squaresOrder, type Concept, type Status } from "./studyModel";

const SELECTED_RING = "0 0 0 1.5px var(--bg), 0 0 0 3px var(--brand-forest)";

function Trend({ points }: { points: number }) {
  if (points === 0) return null;
  const up = points > 0;
  return (
    <span className={`chip ${up ? "chip--accent" : "chip--err"}`} style={{ alignSelf: "flex-start" }}>
      {up ? "+" : "−"}{Math.abs(points)}% this week
    </span>
  );
}

function Square({ concept, selected, faded, onToggle }: { concept: Concept; selected: boolean; faded: boolean; onToggle: () => void }) {
  const label = `${concept.name} · ${ST_LABEL[concept.st]}`;
  return (
    <button className={s.hoverSeg} onClick={onToggle} title={label} aria-label={label}
      style={{ width: 14, height: 14, flexShrink: 0, padding: 0, border: 0, borderRadius: "var(--r-xs)", background: TC[concept.st], opacity: faded ? 0.3 : 1, boxShadow: selected ? SELECTED_RING : "none", cursor: "pointer" }} />
  );
}

/** One legend entry, the Dashboard mastery legend's: a round dot, the count, the state. */
function LegendChip({ status, count, on, onToggle }: { status: Status; count: number; on: boolean; onToggle: () => void }) {
  return (
    <button aria-pressed={on} className={on ? undefined : s.hoverLegend} onClick={onToggle} title="Highlight these on the roadmap"
      style={{ display: "inline-flex", alignItems: "center", gap: 5, height: 22, padding: "0 8px 0 6px", border: 0, borderRadius: "var(--r-full)", background: on ? "var(--sap-100)" : "transparent", ...INHERIT_FONT, fontSize: "var(--fs-xs)", color: on ? "var(--text)" : "var(--text-muted)", cursor: "pointer" }}>
      <StatusDot st={status} size={7} />
      <span>{count} {ST_LABEL[status]}</span>
    </button>
  );
}

type BandProps = {
  /** "Ready for <exam>", or the course's name when the figure is the course's. */
  label: string;
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
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      <div role="img" aria-label={`Overall mastery ${ready.pct} percent`} style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
        {squaresOrder(concepts).map(t => (
          <Square key={t.id} concept={t} selected={t.id === selectedId} faded={!!level && t.st !== level}
            onToggle={() => onSelect(t.id === selectedId ? null : t.id)} />
        ))}
      </div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: "2px 4px", marginLeft: -6 }}>
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
  return (
    // Centred against the Up Next block beside it. Nothing here changes height
    // with the selected concept, so centring never makes the figure jump. A
    // concept's missing prerequisite is marked on its roadmap tile.
    <div style={{ position: "relative", alignSelf: "stretch", display: "flex", flexDirection: "column", justifyContent: "center", gap: 14, minWidth: 0 }}>
      <div style={{ display: "flex", alignItems: "flex-end", gap: 14 }}>
        <span data-testid="readiness-pct" style={{ fontFamily: DISPLAY, fontSize: 42, fontWeight: 600, lineHeight: 1, letterSpacing: "-0.02em" }}>{measured ? `${ready.pct}%` : "–"}</span>
        <div style={{ display: "flex", flexDirection: "column", gap: 3, paddingBottom: 2 }}>
          <span style={{ fontSize: "var(--fs-base)", lineHeight: 1.3, fontWeight: 600 }}>{label}</span>
          <Trend points={ready.trend} />
        </div>
      </div>
      {measured && <ConceptKey {...props} />}
    </div>
  );
}
