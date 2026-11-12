"use client";
/**
 * Recent Activity: the course's latest quizzes, flashcard reviews and study
 * guides. The rail shows the newest few and never grows past them (expanding
 * it in place pushed the page far below the fold); the rest open in a modal
 * that scrolls inside itself.
 */
import React from "react";
import { INHERIT_FONT } from "@/lib/inheritFont";
import { RECENT_SHOWN, type RecentRow } from "./hubModel";
import { ELLIPSIS, Glyph, TOOL } from "./hubUi";
import s from "./StudyHub.module.css";
import { StudyModal } from "./StudyModal";

type Chip = RecentRow["chips"][number];

/** A concept's mastery change from the quiz; clicking it selects the concept. */
function DeltaChip({ chip, onPick }: { chip: Chip; onPick: () => void }) {
  const up = chip.delta >= 0;
  return (
    <button onClick={onPick} title="Mastery change from this quiz"
      style={{ display: "inline-flex", alignItems: "center", gap: 5, height: 22, padding: "0 8px", border: 0, borderRadius: 11, background: up ? "var(--sap-100)" : "var(--err-soft)", color: "var(--text)", ...INHERIT_FONT, fontSize: "var(--fs-xs)", whiteSpace: "nowrap", flexShrink: 0, cursor: "pointer" }}>
      {chip.name}<span style={{ fontWeight: 600, color: up ? "var(--sap-600)" : "var(--err)" }}>{up ? "+" : "−"}{Math.abs(chip.delta)}%</span>
    </button>
  );
}

/** One row: the rail shows the newest few, the "Show all" modal every one. */
function Row({ row, onPickConcept }: { row: RecentRow; onPickConcept: (conceptId: string) => void }) {
  const look = TOOL[row.kind];
  return (
    <div style={{ display: "grid", gridTemplateColumns: "28px minmax(0, 1fr)", columnGap: 10, padding: "8px 0" }}>
      <span style={{ width: 28, height: 28, borderRadius: 7, background: look.bg, color: look.fg, display: "flex", alignItems: "center", justifyContent: "center" }}><Glyph name={look.icon} size={13} /></span>
      <div style={{ minWidth: 0, display: "flex", flexDirection: "column", gap: 4 }}>
        <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
          <span style={{ flex: 1, minWidth: 0 }}>
            <span style={{ display: "block", fontSize: "var(--fs-md)", fontWeight: 600, ...ELLIPSIS }}>{row.title}</span>
            <span style={{ display: "block", fontSize: "var(--fs-sm)", color: "var(--text-muted)" }}>{row.meta}</span>
          </span>
          {row.result && <span style={{ fontSize: "var(--fs-md)", fontWeight: 600, color: row.resultColor, whiteSpace: "nowrap" }}>{row.result}</span>}
        </div>
        {row.chips.length > 0 && (
          <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
            {row.chips.map(ch => <DeltaChip key={ch.id} chip={ch} onPick={() => onPickConcept(ch.id)} />)}
          </div>
        )}
      </div>
    </div>
  );
}

export function RecentActivity({ rows, onPickConcept, onShowAll }: {
  /** Newest first. */
  rows: RecentRow[];
  onPickConcept: (conceptId: string) => void;
  onShowAll: () => void;
}) {
  return (
    <section aria-label="Recent activity" style={{ display: "flex", flexDirection: "column", gap: 2, paddingTop: 16, borderTop: "1px solid var(--border)" }}>
      <span className="label-micro" style={{ marginBottom: 6 }}>Recent Activity</span>
      {rows.length === 0 && <span style={{ fontSize: "var(--fs-md)", color: "var(--text-muted)" }}>Quizzes, flashcards, and study guides for this course will show up here.</span>}
      {rows.slice(0, RECENT_SHOWN).map(row => <Row key={row.key} row={row} onPickConcept={onPickConcept} />)}
      {rows.length > RECENT_SHOWN && (
        <button type="button" className="btn btn--ghost btn--sm" data-testid="recent-toggle" aria-haspopup="dialog"
          onClick={onShowAll}
          // -10px: the ghost button's own side padding, so its label lines
          // up with the row icons above it.
          style={{ alignSelf: "flex-start", marginTop: 4, marginLeft: -10, color: "var(--text-dim)" }}>
          Show all {rows.length} <span aria-hidden="true">→</span>
        </button>
      )}
    </section>
  );
}

export function RecentActivityModal({ rows, courseLabel, isMobile, onPickConcept, onClose }: {
  rows: RecentRow[];
  courseLabel: string;
  isMobile: boolean;
  onPickConcept: (conceptId: string) => void;
  onClose: () => void;
}) {
  return (
    <StudyModal open onClose={onClose} label="Recent activity" width={480} maxHeight={640} top={isMobile ? 40 : 120} gap={4}>
      <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", gap: 12, paddingBottom: 8 }}>
        <span className="h-serif" style={{ fontSize: "var(--fs-2xl)" }}>Recent Activity</span>
        <span style={{ fontSize: "var(--fs-sm)", color: "var(--text-muted)" }}>{courseLabel}</span>
      </div>
      {/* The LIST scrolls, not the dialog: the title and Close stay put,
          and the scrollbar sits inside the card (in the gutter this margin
          and padding make) instead of riding the dialog's rounded edge. */}
      <div className={s.catScroll} data-testid="recent-all"
        style={{ flex: "1 1 auto", minHeight: 0, overflowY: "auto", overscrollBehavior: "contain", marginRight: -14, paddingRight: 14 }}>
        {rows.map(row => <Row key={row.key} row={row} onPickConcept={onPickConcept} />)}
      </div>
      <div style={{ display: "flex", justifyContent: "flex-end", paddingTop: 12, marginTop: 8, borderTop: "1px solid var(--border)" }}>
        <button type="button" className="btn" onClick={onClose} style={{ height: 36, padding: "0 16px" }}>Close</button>
      </div>
    </StudyModal>
  );
}
