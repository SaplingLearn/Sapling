"use client";
/**
 * Recent Activity: the course's latest quizzes, flashcard reviews and study
 * guides. The rail shows the newest few and never grows past them (expanding
 * it in place pushed the page far below the fold); the rest open in a modal
 * that scrolls inside itself.
 */
import React from "react";
import Link from "next/link";
import { RECENT_SHOWN, type RecentRow } from "./hubModel";
import { Glyph, TOOL } from "./hubUi";
import s from "./StudyHub.module.css";
import { StudyModal } from "./StudyModal";
import { cn } from "@/lib/cn";

type Chip = RecentRow["chips"][number];

/** A concept's mastery change from the quiz; clicking it selects the concept. */
function DeltaChip({ chip, onPick }: { chip: Chip; onPick: () => void }) {
  const up = chip.delta >= 0;
  return (
    <button onClick={onPick} title="Mastery change from this quiz"
      className={cn("inline-flex items-center gap-[5px] h-5.5 py-0 px-2 border-0 rounded-[11px] text-text [font-family:inherit] [font-weight:inherit] [font-style:inherit] [line-height:inherit] text-xs whitespace-nowrap shrink-0 cursor-pointer", up ? "bg-sap-100" : "bg-err-soft")}>
      {chip.name}<span className={cn("font-semibold", up ? "text-sap-600" : "text-err")}>{up ? "+" : "−"}{Math.abs(chip.delta)}%</span>
    </button>
  );
}

/** One row: the rail shows the newest few, the "Show all" modal every one.
 *  A row that leads somewhere (a study guide, to its reader) is a link. */
function Row({ row, onPickConcept }: { row: RecentRow; onPickConcept: (conceptId: string) => void }) {
  const look = TOOL[row.kind];
  const inside = (
    <>
      <span className="w-7 h-7 rounded-[7px] flex items-center justify-center" style={{ background: look.bg, color: look.fg }}><Glyph name={look.icon} size={13} /></span>
      <div className="min-w-0 flex flex-col gap-1">
        <div className="flex items-baseline gap-2.5">
          <span className="flex-1 min-w-0">
            <span className="block text-md font-semibold whitespace-nowrap overflow-hidden text-ellipsis">{row.title}</span>
            <span className="block text-sm text-text-muted">{row.meta}</span>
          </span>
          {row.result && <span className="text-md font-semibold whitespace-nowrap" style={{ color: row.resultColor }}>{row.result}</span>}
        </div>
        {row.chips.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {row.chips.map(ch => <DeltaChip key={ch.id} chip={ch} onPick={() => onPickConcept(ch.id)} />)}
          </div>
        )}
      </div>
    </>
  );
  if (!row.href) return <div className="grid grid-cols-[28px_minmax(0,_1fr)] gap-x-2.5 py-2 px-0">{inside}</div>;
  return (
    <Link href={row.href} data-testid={`recent-${row.key}`} className="grid grid-cols-[28px_minmax(0,_1fr)] gap-x-2.5 py-2 px-0 text-inherit no-underline">
      {inside}
    </Link>
  );
}

export function RecentActivity({ rows, onPickConcept, onShowAll }: {
  /** Newest first. */
  rows: RecentRow[];
  onPickConcept: (conceptId: string) => void;
  onShowAll: () => void;
}) {
  return (
    <section aria-label="Recent activity" className="flex flex-col gap-0.5 pt-4 border-t border-t-border">
      <span className="label-micro mb-1.5">Recent Activity</span>
      {rows.length === 0 && <span className="text-md text-text-muted">Quizzes, flashcards, and study guides for this course will show up here.</span>}
      {rows.slice(0, RECENT_SHOWN).map(row => <Row key={row.key} row={row} onPickConcept={onPickConcept} />)}
      {rows.length > RECENT_SHOWN && (
        <button type="button" className="btn btn--ghost btn--sm self-start mt-1 -ml-2.5 text-text-dim" data-testid="recent-toggle" aria-haspopup="dialog"
          onClick={onShowAll}
          // -10px: the ghost button's own side padding, so its label lines
          // up with the row icons above it.
>
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
      <div className="flex items-baseline justify-between gap-3 pb-2">
        <span className="h-serif text-2xl">Recent Activity</span>
        <span className="text-sm text-text-muted">{courseLabel}</span>
      </div>
      {/* The LIST scrolls, not the dialog: the title and Close stay put,
          and the scrollbar sits inside the card (in the gutter this margin
          and padding make) instead of riding the dialog's rounded edge. */}
      <div className={cn(s.catScroll, "flex-[1_1_auto] min-h-0 overflow-y-auto [overscroll-behavior:contain] -mr-3.5 pr-3.5")} data-testid="recent-all">
        {rows.map(row => <Row key={row.key} row={row} onPickConcept={onPickConcept} />)}
      </div>
      <div className="flex justify-end pt-3 mt-2 border-t border-t-border">
        <button type="button" className="btn h-9 py-0 px-4" onClick={onClose}>Close</button>
      </div>
    </StudyModal>
  );
}
