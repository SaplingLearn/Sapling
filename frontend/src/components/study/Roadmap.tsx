"use client";
/**
 * The roadmap: the course's concepts in columns (its own categories, or
 * prerequisite layers when it has none), each a list of tiles. A long column
 * folds its mastered tiles into "N more mastered".
 */
import React from "react";
import { INHERIT_FONT } from "@/lib/inheritFont";
import { Icon } from "../Icon";
import { cardsFor, type RoadmapColumn } from "./hubModel";
import { ELLIPSIS } from "./hubUi";
import { RoadmapTile } from "./RoadmapTile";
import s from "./StudyHub.module.css";
import { TC } from "./studyModel";
import type { SetHub } from "./useHubState";
import type { ToolNav } from "./useToolNav";

/* auto-fit, not auto-fill: the columns share the whole row instead of leaving
   empty tracks (a blank strip) to their right. A course with only one or two
   columns is capped so its tiles don't stretch into banners.
   At most four columns across, at any width: a track is never narrower than a
   quarter of the row (less the three 16px gaps between four), so a fifth
   cannot fit beside four and a course with more categories wraps onto a second
   row. Below ~850px that quarter is under 200px and the 200px floor takes
   over, wrapping earlier as before. The 0.1px keeps four quarters from
   rounding up past the row's width, which would leave room for only three. */
const TRACKS = "repeat(auto-fit, minmax(max(200px, calc((100% - 48px) / 4 - 0.1px)), 1fr))";
const gridWidth = (columns: number) => (columns < 3 ? columns * 336 - 16 : undefined);

/** A column's name, its mastered count, and a bar per concept. */
function ColumnHead({ column }: { column: RoadmapColumn }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 5, paddingBottom: 2 }}>
      <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", gap: 8 }}>
        <span style={{ fontSize: "var(--fs-md)", fontWeight: 600, ...ELLIPSIS }}>{column.label}</span>
        <span className="mono" style={{ fontSize: "var(--fs-xs)", color: "var(--text-dim)", flexShrink: 0 }}>{column.frac}</span>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(8, minmax(0, 1fr))", gap: "4px 3px" }}>
        {column.bars.map((b, i) => <span key={i} className={s.bar} style={{ height: 4, borderRadius: "var(--r-full)", background: b }} />)}
      </div>
    </div>
  );
}

/** "N more mastered" / "Show Less": opens and closes a column's fold. */
function FoldToggle({ column, onToggle }: { column: RoadmapColumn; onToggle: () => void }) {
  return (
    <button className={s.hoverMore} onClick={onToggle}
      style={{ display: "flex", alignItems: "center", gap: 8, height: 32, padding: "0 10px", border: "1px dashed var(--border-strong)", borderRadius: "var(--r-md)", background: "transparent", ...INHERIT_FONT, fontSize: "var(--fs-sm)", fontWeight: 600, color: "var(--text-dim)", cursor: "pointer" }}>
      <span style={{ display: "flex", gap: 3 }}>{column.hidden.map(x => <span key={x.t.id} style={{ width: 7, height: 7, borderRadius: 2, background: TC[x.t.st] }} />)}</span>
      <span style={{ flex: 1, textAlign: "left", whiteSpace: "nowrap" }}>{column.open ? "Show Less" : `${column.hidden.length} more mastered`}</span>
      <span style={{ display: "flex", flexShrink: 0, transform: column.open ? "rotate(180deg)" : "none" }}><Icon name="chevron-down" size={10} /></span>
    </button>
  );
}

/** Key it on the course, so a course change replays its entrance. */
export interface RoadmapProps {
  columns: RoadmapColumn[];
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

export function Roadmap({ columns, cards, tileMenu, openCols, quizShown, nav, set, closeTileMenu }: RoadmapProps) {
  /* Stacking: every column is its own stacking context (its colEnter
     opacity/transform animation), and so is any hovered (lifted) or dimmed
     tile. A z-index on the menu alone is therefore trapped and later
     tiles/columns paint over it, so the column AND the tile that own the open
     menu are lifted above their siblings. An open menu can also hang past the
     section's bottom edge; lifting the section keeps it over whatever follows
     (the rail, once the narrow layout stacks it underneath). */
  const lift = (on: boolean) => (on ? 2 : undefined);
  return (
    <section aria-label="Roadmap" className={`${s.areaRoadmap} ${s.paneEnter}`}
      style={{ position: "relative", zIndex: lift(!!tileMenu), padding: "16px 6px 24px 0" }}>
      <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", marginBottom: 12 }}>
        <span className="label-micro">Roadmap</span>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: TRACKS, gap: "20px 16px", alignItems: "start", maxWidth: gridWidth(columns.length) }}>
        {columns.map((col, ci) => (
          <div key={col.key} className={s.colEnter}
            style={{ "--i": Math.min(ci, 6), position: "relative", zIndex: lift(col.shown.some(x => x.t.id === tileMenu)), display: "flex", flexDirection: "column", gap: 6, minWidth: 0 } as React.CSSProperties}>
            <ColumnHead column={col} />
            {col.shown.map(tile => (
              <RoadmapTile key={tile.t.id} tile={tile} menuOpen={tileMenu === tile.t.id} cardCount={cardsFor(cards, tile.t.name)}
                quizShown={quizShown} nav={nav} set={set} closeTileMenu={closeTileMenu} />
            ))}
            {col.hidden.length > 0 && <FoldToggle column={col} onToggle={() => set({ openCols: { ...openCols, [col.key]: !col.open } })} />}
          </div>
        ))}
      </div>
      {columns.length === 0 && <div style={{ fontSize: "var(--fs-md)", color: "var(--text-muted)" }}>Concepts from this course&apos;s knowledge graph will appear here.</div>}
    </section>
  );
}
