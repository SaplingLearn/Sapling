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
import { ROADMAP_ID } from "./hubUi";
import rm from "./Roadmap.module.css";
import { RoadmapTile } from "./RoadmapTile";
import s from "./StudyHub.module.css";
import { TC, type ExamScope } from "./studyModel";
import { useFlip } from "./useFlip";
import type { SetHub } from "./useHubState";
import type { ToolNav } from "./useToolNav";

/* The tracks (auto-fit, at most four across) are `.grid`'s, in Roadmap.module.css. */
/** Below this many columns the grid is capped (`.gridNarrow`), so a course's
 *  one or two columns don't stretch into banners. */
const NARROW_UNDER = 3;
/** Columns past this many enter on the same beat as the last (`.colEnter`'s stagger). */
const STAGGER_CAP = 6;

/** A column's name, its mastered count, and a bar per concept. */
function ColumnHead({ column }: { column: RoadmapColumn }) {
  return (
    <div className={rm.colHead}>
      <div className={rm.colTitleRow}>
        <span className={`${rm.colTitle} ${s.ellipsis}`}>{column.label}</span>
        <span key={column.frac} className={`mono ${rm.colFrac}`} data-flip={`frac:${column.key}:${column.frac}`} data-flip-how="fade">{column.frac}</span>
      </div>
      <div className={rm.bars}>
        {column.bars.map((b, i) => <span key={i} className={`${s.bar} ${rm.barShape}`} style={{ background: b }} />)}
      </div>
    </div>
  );
}

/** "N more mastered" / "Show Less": opens and closes a column's fold. */
function FoldToggle({ column, onToggle }: { column: RoadmapColumn; onToggle: () => void }) {
  return (
    <button className={`${rm.fold} ${s.hoverMore}`} onClick={onToggle} data-flip={`fold:${column.key}`}>
      <span className={rm.foldDots}>{column.hidden.map(x => <span key={x.t.id} className={rm.foldDot} style={{ background: TC[x.t.st] }} />)}</span>
      <span className={rm.foldLabel}>{column.open ? "Show Less" : `${column.hidden.length} more mastered`}</span>
      <span className={column.open ? `${rm.foldChevron} ${rm.foldChevronOpen}` : rm.foldChevron}><Icon name="chevron-down" size={10} /></span>
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
     opacity/transform animation), and so is any lifted tile. A z-index on the menu alone is therefore trapped and later
     tiles/columns paint over it, so the column AND the tile that own the open
     menu are lifted above their siblings. An open menu can also hang past the
     section's bottom edge; lifting the section keeps it over whatever follows
     (the rail, once the narrow layout stacks it underneath). */
  const lift = (on: boolean) => (on ? ` ${s.lifted}` : "");
  const grid = React.useRef<HTMLDivElement | null>(null);
  useFlip(grid, scope?.id ?? "");
  return (
    <section id={ROADMAP_ID} aria-label="Roadmap" className={`${s.areaRoadmap} ${s.paneEnter} ${rm.section}${lift(!!tileMenu)}`}>
      <div className={rm.head}>
        <span className={`label-micro ${rm.headLabel}`}>Roadmap</span>
        {scope && <span data-testid="roadmap-exam-caption" className={`${rm.caption} ${s.ellipsis}`}>{scopeCaption(scope)}</span>}
      </div>
      {/* Positioned, and its rows packed to the top, for useFlip: it reads each
          column's place against this box and tweens this box's height. */}
      <div ref={grid} className={columns.length < NARROW_UNDER ? `${rm.grid} ${rm.gridNarrow}` : rm.grid}
        style={{ "--cols": columns.length } as React.CSSProperties}>
        {columns.map((col, ci) => (
          <div key={col.key} className={`${s.colEnter} ${rm.column}${lift(col.shown.some(x => x.t.id === tileMenu))}`} data-flip={`col:${col.key}`}
            style={{ "--i": Math.min(ci, STAGGER_CAP) } as React.CSSProperties}>
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
      {columns.length === 0 && !pending && <div className={rm.emptyNote}>Concepts from this course&apos;s knowledge graph will appear here.</div>}
    </section>
  );
}
