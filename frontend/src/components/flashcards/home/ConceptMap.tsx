"use client";
/**
 * The concept map: the course's concepts in the Study hub's roadmap columns
 * (units from the outline, the hub's fallback layers otherwise), at most four
 * across. Each concept is a tile that is one big checkbox; a column's header
 * ticks or unticks the whole column and reads "mixed" when only part is.
 *
 * The last column, "Your own", holds what is not a course concept: decks whose
 * topic is something else, and the concepts the student adds by name with the
 * field under the map. An added one has no cards until Start generates them,
 * and until then it can be taken off again.
 */
import React from "react";
import Link from "next/link";
import hub from "../../study/StudyHub.module.css";
import { ST_LABEL, TC } from "../../study/studyModel";
import {
  cardsLabel,
  columnCheck,
  hasName,
  type MapColumn,
  type MapItem,
} from "./flashcardsModel";
import { columnPalette } from "./decksModel";
import h from "./home.module.css";

export function ConceptMap({
  columns, hasConcepts, hasCourse, selected, onToggle, onColumn, onRemoveOwn,
}: {
  columns: MapColumn[];
  /** False for a course the graph has nothing for yet. */
  hasConcepts: boolean;
  hasCourse: boolean;
  selected: string[];
  onToggle: (name: string) => void;
  onColumn: (names: string[], on: boolean) => void;
  onRemoveOwn: (name: string) => void;
}) {
  return (
    <section aria-label="Concepts" className={h.map}>
      <div className={h.mapHead}>
        <span className="label-micro">Concepts</span>
      </div>
      {!hasConcepts && (
        <p className={h.quiet} style={{ marginBottom: columns.length ? 16 : 0 }}>
          {hasCourse
            ? <>No concepts for this course yet. Upload its material in the <Link href="/library">Library</Link> and the concepts will show up here.</>
            : <>Add a course to see its concepts here. Material you upload in the <Link href="/library">Library</Link> becomes the concepts you can make cards for.</>}
        </p>
      )}
      {/* A course with one or two columns is capped, as on the hub, so its
          tiles do not stretch into banners. */}
      <div className={h.columns} style={{ maxWidth: columns.length > 0 && columns.length < 3 ? columns.length * 336 - 16 : undefined }}>
        {columns.map((col, i) => (
          <Column key={col.label} col={col} order={i} selected={selected} onToggle={onToggle} onColumn={onColumn} onRemoveOwn={onRemoveOwn} />
        ))}
      </div>
    </section>
  );
}

function Column({
  col, order, selected, onToggle, onColumn, onRemoveOwn,
}: {
  col: MapColumn;
  order: number;
  selected: string[];
  onToggle: (name: string) => void;
  onColumn: (names: string[], on: boolean) => void;
  onRemoveOwn: (name: string) => void;
}) {
  const { ticked, state } = columnCheck(selected, col.items);
  const box = React.useRef<HTMLInputElement | null>(null);
  // `indeterminate` is a DOM property with no attribute: it is what makes the
  // box read "mixed" to assistive tech and draw its dash.
  React.useEffect(() => {
    if (box.current) box.current.indeterminate = state === "some";
  }, [state]);
  return (
    <div className={`${hub.colEnter} ${h.column}`} data-palette={columnPalette(col.label, order)} style={{ "--i": Math.min(order, 6) } as React.CSSProperties}>
      <label className={h.colHead}>
        <input
          ref={box}
          type="checkbox"
          className={h.check}
          checked={state === "all"}
          aria-label={`Select all of ${col.label}`}
          onChange={() => onColumn(col.items.map(item => item.name), state !== "all")}
        />
        <span className={h.colLabel}>{col.label}</span>
        <span className={`mono ${h.colCount}`}>{ticked}/{col.items.length}</span>
      </label>
      {col.items.map(item => (
        <Tile key={item.id} item={item} on={hasName(selected, item.name)} onToggle={onToggle} onRemove={onRemoveOwn} />
      ))}
    </div>
  );
}

function Tile({
  item, on, onToggle, onRemove,
}: {
  item: MapItem;
  on: boolean;
  onToggle: (name: string) => void;
  onRemove: (name: string) => void;
}) {
  return (
    <div className={`${hub.tile} ${h.tile}${on ? ` ${hub.tileSel} ${h.tileOn}` : ""}`} data-testid={`flashcards-tile-${item.id}`}>
      {/* The label is the whole tile but for the remove control, which sits
          beside it: a button inside a label would be part of the checkbox. */}
      <label className={h.tileHit}>
        <input type="checkbox" className={h.check} checked={on} onChange={() => onToggle(item.name)} />
        <span className={h.tileText}>
          <span className={h.tileName}>{item.name}</span>
          <span className={h.tileMeta}>{cardsLabel(item.cards, item.due)}</span>
        </span>
        {item.status && <span aria-hidden="true" className={h.dot} style={{ background: TC[item.status] }} title={ST_LABEL[item.status]} />}
      </label>
      {item.custom && (
        <button type="button" className={h.tileRemove} aria-label={`Remove ${item.name}`} title="Remove this concept" onClick={() => onRemove(item.name)}>
          <svg width="10" height="10" viewBox="0 0 12 12" aria-hidden="true"><path d="M2 2l8 8M10 2l-8 8" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" /></svg>
        </button>
      )}
    </div>
  );
}
