"use client";
/**
 * The roadmap: the course's concepts in columns (its own categories, or
 * prerequisite layers when it has none), each a list of tiles. A long column
 * folds its mastered tiles into "N more mastered".
 *
 * It follows the selected exam: `columns` then holds only the concepts that
 * exam covers, a caption says how many, and a change of exam is animated as
 * the same roadmap rearranging (./useFlip.ts, over the `data-flip` items).
 */
import React from "react";
import { Icon } from "../Icon";
import { cardsFor, type RoadmapColumn } from "./hubModel";
import { RoadmapTile } from "./RoadmapTile";
import s from "./StudyHub.module.css";
import { TC, type ExamScope } from "./studyModel";
import { useFlip } from "./useFlip";
import type { SetHub } from "./useHubState";
import type { ToolNav } from "./useToolNav";
import { cn } from "@/lib/cn";

const gridWidth = (columns: number) => (columns < 3 ? columns * 336 - 16 : undefined);

/** A column's name, its mastered count, and a bar per concept. */
function ColumnHead({ column }: { column: RoadmapColumn }) {
  return (
    <div className="flex flex-col gap-[5px] pb-0.5">
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-md font-semibold whitespace-nowrap overflow-hidden text-ellipsis">{column.label}</span>
        <span key={column.frac} className="mono text-xs text-text-dim shrink-0" data-flip={`frac:${column.key}:${column.frac}`} data-flip-how="fade">{column.frac}</span>
      </div>
      <div className="grid grid-cols-[repeat(8,_minmax(0,_1fr))] gap-y-1 gap-x-[3px]">
        {column.bars.map((b, i) => <span key={i} className={cn(s.bar, "h-1 rounded-[var(--r-full)]")} style={{ background: b }} />)}
      </div>
    </div>
  );
}

/** "N more mastered" / "Show Less": opens and closes a column's fold. */
function FoldToggle({ column, onToggle }: { column: RoadmapColumn; onToggle: () => void }) {
  return (
    <button className={cn(s.hoverMore, "flex items-center gap-2 h-8 py-0 px-2.5 border border-dashed border-border-strong rounded-md [background:transparent] [font-family:inherit] [font-style:inherit] [line-height:inherit] text-sm font-semibold text-text-dim cursor-pointer")} onClick={onToggle} data-flip={`fold:${column.key}`}>
      <span className="flex gap-[3px]">{column.hidden.map(x => <span key={x.t.id} className="w-[7px] h-[7px] rounded-[2px]" style={{ background: TC[x.t.st] }} />)}</span>
      <span className="flex-1 text-left whitespace-nowrap">{column.open ? "Show Less" : `${column.hidden.length} more mastered`}</span>
      <span className={cn("flex shrink-0", column.open ? "[transform:rotate(180deg)]" : "[transform:none]")}><Icon name="chevron-down" size={10} /></span>
    </button>
  );
}

/** "2 concepts on Exam 2": why the roadmap is shorter than the course. */
const scopeCaption = (scope: ExamScope) =>
  `${scope.ids.size} ${scope.ids.size === 1 ? "concept" : "concepts"} on ${scope.title}`;

/** Key it on the course, so a course change replays its entrance. */
export interface RoadmapProps {
  columns: RoadmapColumn[];
  /** The course's categories are still being read, so `columns` is empty
   *  because nothing can be grouped YET — not because the course has no
   *  concepts. Keeps the empty state from claiming the latter. */
  pending?: boolean;
  /** What the selected exam covers (and `columns` is cut down to); null when
   *  no exam is selected or it has no concepts linked. */
  scope: ExamScope | null;
  /** Flashcards per concept name (hubModel's `cardCounts`). */
  cards: Map<string, number>;
  /** The concept whose "..." menu is open. */
  tileMenu: string | null;
  openCols: Record<string, boolean>;
  quizShown: boolean;
  nav: ToolNav;
  set: SetHub;
  closeTileMenu: (conceptId: string) => void;
}

export function Roadmap({ columns, pending = false, scope, cards, tileMenu, openCols, quizShown, nav, set, closeTileMenu }: RoadmapProps) {
  /* Stacking: every column is its own stacking context (its colEnter
     opacity/transform animation), and so is any hovered (lifted) or dimmed
     tile. A z-index on the menu alone is therefore trapped and later
     tiles/columns paint over it, so the column AND the tile that own the open
     menu are lifted above their siblings. An open menu can also hang past the
     section's bottom edge; lifting the section keeps it over whatever follows
     (the rail, once the narrow layout stacks it underneath). */
  const lift = (on: boolean) => (on ? 2 : undefined);
  const grid = React.useRef<HTMLDivElement | null>(null);
  useFlip(grid, scope?.id ?? "");
  return (
    <section aria-label="Roadmap" className={cn(`${s.areaRoadmap} ${s.paneEnter}`, "relative pt-4 pr-1.5 pb-6 pl-0")}
      style={{ zIndex: lift(!!tileMenu) }}>
      <div className="flex items-baseline gap-2.5 mb-3">
        <span className="label-micro shrink-0">Roadmap</span>
        {scope && <span data-testid="roadmap-exam-caption" className="min-w-0 text-sm text-text-muted whitespace-nowrap overflow-hidden text-ellipsis">{scopeCaption(scope)}</span>}
      </div>
      {/* Positioned, and its rows packed to the top, for useFlip: it reads each
          column's place against this box and tweens this box's height. */}
      <div ref={grid} className="relative grid grid-cols-[repeat(auto-fit,_minmax(max(200px,_calc((100%_-_48px)_/_4_-_0.1px)),_1fr))] gap-y-5 gap-x-4 [align-items:start] [align-content:start]" style={{ maxWidth: gridWidth(columns.length) }}>
        {columns.map((col, ci) => (
          <div key={col.key} className={cn(s.colEnter, "relative flex flex-col gap-1.5 min-w-0")} data-flip={`col:${col.key}`}
            style={{ "--i": Math.min(ci, 6), zIndex: lift(col.shown.some(x => x.t.id === tileMenu)) } as React.CSSProperties}>
            <ColumnHead column={col} />
            {col.shown.map(tile => (
              <RoadmapTile key={tile.t.id} tile={tile} menuOpen={tileMenu === tile.t.id} cardCount={cardsFor(cards, tile.t.name)}
                quizShown={quizShown} nav={nav} set={set} closeTileMenu={closeTileMenu} />
            ))}
            {col.hidden.length > 0 && <FoldToggle column={col} onToggle={() => set({ openCols: { ...openCols, [col.key]: !col.open } })} />}
          </div>
        ))}
      </div>
      {/* Never while `pending`: "this course has nothing" is a claim about
          the student's data, and a course mid-read has not made it yet. */}
      {columns.length === 0 && !pending && <div className="text-md text-text-muted">Concepts from this course&apos;s knowledge graph will appear here.</div>}
    </section>
  );
}
