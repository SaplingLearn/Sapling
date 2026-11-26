"use client";
// The redesigned calendar's four views (behind `calendar_v2`; design:
// calendar/v2/__fixtures__/*.design.html): Agenda (the default: what is due,
// soonest first), Month, Week and Semester (each course on its own line, week
// by week). Every item opens the same panel (ItemPanel.tsx).
import React from "react";
import { plural } from "@/lib/learningCopy";
import {
  WEEKDAYS, countdown, daysBetween, loadText, shortDate, timelinePos, weekdayShort,
  type AgendaGroup, type CalItem, type DayCell, type WeekLoad,
} from "./calendarModel";
import type { ExamReadiness } from "./useExamReadiness";
import styles from "./CalendarV2.module.css";

export const VIEWS_COPY = {
  earlier: (n: number, first: CalItem | undefined) =>
    n === 1 && first ? `Show 1 earlier date (${first.title}, ${shortDate(first.day)})` : `Show ${plural(n, "earlier date")}`,
  hideEarlier: "Hide earlier dates",
  earlierName: "Earlier",
  nothingAhead: "Nothing else is due. Import a syllabus or add a date to fill it in.",
  ready: (r: Pick<ExamReadiness, "ready" | "total">) => `${r.ready} of ${plural(r.total, "concept")} ready`,
  prepare: "Prepare",
  more: (n: number) => `+${n} more`,
  today: "Today",
  key: "Key",
  keyNote: "The bar under each week: how much is due that week.",
  exam: "Exam",
  quiz: "Quiz",
  homework: "Homework",
} as const;

const PILLS_SHOWN = 3;

export function KindLabel({ kind }: { kind: CalItem["kind"] }) {
  const cls = kind === "Exam" ? styles.kindExam : kind === "Quiz" ? styles.kindQuiz : styles.kindHomework;
  return <span className={cls}>{kind}</span>;
}

export function Swatch({ color }: { color: string }) {
  return <span aria-hidden className={styles.swatch} style={{ "--course": color } as React.CSSProperties} />;
}

function Readiness({ r }: { r: ExamReadiness }) {
  const pct = r.total ? Math.round((r.ready / r.total) * 100) : 0;
  return (
    <span className={styles.readiness}>
      <span className={styles.meter} role="meter" aria-label="Concepts ready" aria-valuemin={0} aria-valuemax={r.total}
        aria-valuenow={r.ready} aria-valuetext={VIEWS_COPY.ready(r)}>
        <i style={{ "--fill": `${pct}%` } as React.CSSProperties} />
      </span>
      {VIEWS_COPY.ready(r)}
    </span>
  );
}

export type ItemProps = {
  today: Date;
  readiness: ReadonlyMap<string, ExamReadiness>;
  prepareHref: (item: CalItem) => string | null;
  onOpen: (item: CalItem, from: HTMLElement) => void;
};

function AgendaRow({ item, today, readiness, prepareHref, onOpen }: ItemProps & { item: CalItem }) {
  const days = daysBetween(today, item.day);
  const r = readiness.get(item.id);
  const href = item.kind === "Exam" && days >= 0 ? prepareHref(item) : null;
  const rowCls = [styles.row, item.kind === "Exam" ? styles.rowExam : "", days < 0 ? styles.rowPast : ""].join(" ");
  return (
    <li className={rowCls} data-testid={`calendar-item-${item.id}`} data-kind={item.kind}>
      <span className={styles.dateBlock} aria-hidden>
        <span className={styles.dow}>{weekdayShort(item.day).toUpperCase()}</span>
        <span className={styles.dayNum}>{item.day.getDate()}</span>
      </span>
      <div className={styles.rowMain}>
        <button type="button" className={styles.titleBtn} onClick={(e) => onOpen(item, e.currentTarget)}
          aria-label={`${item.title}, ${item.course}, ${item.kind}, ${shortDate(item.day)}`}>{item.title}</button>
        <div className={styles.meta}>
          <span className={styles.course}><Swatch color={item.color} />{item.course}</span>
          <KindLabel kind={item.kind} />
          {r && days >= 0 && <Readiness r={r} />}
        </div>
      </div>
      <div className={styles.rowEnd}>
        <span className={`${styles.when} ${days >= 0 && days <= 2 ? styles.whenSoon : ""}`}>{countdown(item.day, today)}</span>
        {href && (
          <a href={href} className={styles.prepare} data-testid={`calendar-prepare-${item.id}`}
            aria-label={`${VIEWS_COPY.prepare} for ${item.title}`}>{VIEWS_COPY.prepare}</a>
        )}
      </div>
    </li>
  );
}

function AgendaSection({ name, range, items, id, ...rest }: ItemProps & { name: string; range: string; items: CalItem[]; id: string }) {
  return (
    <section aria-labelledby={id} className={styles.list} data-testid={`calendar-group-${id}`}>
      <div className={styles.groupHead}>
        <h2 id={id} className={styles.h2}>{name}</h2>
        {range && <span className={styles.dim}>{range}</span>}
      </div>
      <ul className={styles.list}>
        {items.map((it) => <AgendaRow key={it.id} item={it} {...rest} />)}
      </ul>
    </section>
  );
}

export function AgendaView({ earlier, groups, ...rest }: ItemProps & { earlier: CalItem[]; groups: AgendaGroup[] }) {
  const [showEarlier, setShowEarlier] = React.useState(false);
  return (
    <div className={styles.agenda} data-testid="calendar-agenda">
      {earlier.length > 0 && (
        <button type="button" className={styles.textBtn} aria-expanded={showEarlier} data-testid="calendar-earlier"
          onClick={() => setShowEarlier((s) => !s)}>
          {showEarlier ? VIEWS_COPY.hideEarlier : VIEWS_COPY.earlier(earlier.length, earlier[earlier.length - 1])}
        </button>
      )}
      {showEarlier && earlier.length > 0 && (
        <AgendaSection id="calendar-earlier-h" name={VIEWS_COPY.earlierName} range="" items={[...earlier].reverse()} {...rest} />
      )}
      {groups.length === 0 ? <p className={styles.nothing}>{VIEWS_COPY.nothingAhead}</p> : groups.map((g) => (
        <AgendaSection key={g.key} id={`calendar-${g.key}-h`} name={g.name} range={g.range} items={g.items} {...rest} />
      ))}
    </div>
  );
}

function Pill({ item, today, onOpen }: { item: CalItem; today: Date; onOpen: ItemProps["onOpen"] }) {
  const cls = [styles.pill, item.kind === "Exam" ? styles.pillExam : item.kind === "Quiz" ? styles.pillQuiz : "",
    daysBetween(today, item.day) < 0 ? styles.pillPast : ""].join(" ");
  return (
    <button type="button" className={cls} data-testid={`calendar-pill-${item.id}`} onClick={(e) => onOpen(item, e.currentTarget)}
      aria-label={`${item.title}, ${item.course}, ${item.kind}, ${shortDate(item.day)}`}>
      <Swatch color={item.color} />
      <span>{item.kind === "Exam" ? `${item.title} · ${item.course}` : item.title}</span>
    </button>
  );
}

function DayCellView({ cell, today, onOpen, onMore, week = false }: {
  cell: DayCell; today: Date; onOpen: ItemProps["onOpen"]; onMore: (day: Date) => void; week?: boolean;
}) {
  const shown = week ? cell.items : cell.items.slice(0, PILLS_SHOWN);
  const hidden = cell.items.length - shown.length;
  const cls = [styles.cell, week ? styles.weekCell : "", cell.weekend ? styles.cellWeekend : "", cell.today ? styles.cellToday : ""].join(" ");
  const num = [styles.num, cell.today ? styles.numToday : !cell.inMonth ? styles.numOut : cell.past ? styles.numPast : ""].join(" ");
  return (
    <div className={cls} data-testid={`calendar-day-${cell.iso}`} aria-current={cell.today ? "date" : undefined}>
      <div className={styles.cellHead}>
        <span className={num}>{week ? `${weekdayShort(cell.day)} ${cell.day.getDate()}` : cell.day.getDate()}</span>
        {cell.today && <span className={styles.todayWord}>{VIEWS_COPY.today}</span>}
      </div>
      {shown.map((it) => <Pill key={it.id} item={it} today={today} onOpen={onOpen} />)}
      {hidden > 0 && (
        <button type="button" className={styles.moreBtn} onClick={() => onMore(cell.day)}>{VIEWS_COPY.more(hidden)}</button>
      )}
    </div>
  );
}

export function KindKey() {
  return (
    <div className={styles.legend} aria-label={VIEWS_COPY.key}>
      <span className={styles.kindExam}>{VIEWS_COPY.exam}</span>
      <span className={styles.kindQuiz}>{VIEWS_COPY.quiz}</span>
      <span>{VIEWS_COPY.homework}</span>
    </div>
  );
}

export function MonthView({ cells, today, onOpen, onMore }: {
  cells: DayCell[]; today: Date; onOpen: ItemProps["onOpen"]; onMore: (day: Date) => void;
}) {
  return (
    <div className={styles.gridScroll}>
      <div className={styles.grid} data-testid="calendar-month">
        <div className={styles.gridHead} aria-hidden>{WEEKDAYS.map((d) => <span key={d}>{d}</span>)}</div>
        <div className={styles.cells}>
          {cells.map((c) => <DayCellView key={c.iso} cell={c} today={today} onOpen={onOpen} onMore={onMore} />)}
        </div>
      </div>
    </div>
  );
}

export function WeekView({ cells, today, onOpen }: { cells: DayCell[]; today: Date; onOpen: ItemProps["onOpen"] }) {
  return (
    <div className={styles.gridScroll}>
      <div className={`${styles.grid} ${styles.weekGrid}`} data-testid="calendar-week">
        <div className={styles.cells}>
          {cells.map((c) => <DayCellView key={c.iso} cell={c} today={today} onOpen={onOpen} onMore={() => {}} week />)}
        </div>
      </div>
    </div>
  );
}

export interface Lane { id: string; label: string; color: string; items: (CalItem & { row: number })[] }

export function SemesterView({ start, weeks, loads, lanes, today, heavyStart, onOpen }: {
  start: Date; weeks: number; loads: WeekLoad[]; lanes: Lane[]; today: Date; heavyStart: Date | null; onOpen: ItemProps["onOpen"];
}) {
  const todayPos = timelinePos(today, start, weeks);
  const maxCount = Math.max(1, ...loads.map((w) => w.count));
  return (
    <div className={styles.timelineScroll}>
      <section aria-label="Timeline" className={styles.timeline} data-testid="calendar-semester"
        style={{ "--weeks": weeks } as React.CSSProperties}>
        <div className={styles.tlHead}>
          <span className={styles.laneLabel}>Week of</span>
          <div className={styles.weeks}>
            {loads.map((w) => {
              const heavy = !!heavyStart && w.start.getTime() === heavyStart.getTime();
              return (
                <div key={w.label} className={styles.week} data-testid="calendar-week-load">
                  <span className={styles.weekLabel}>{w.label}</span>
                  <span aria-hidden className={`${styles.load} ${w.count === 0 ? styles.loadEmpty : ""} ${heavy ? styles.loadHeavy : ""}`}
                    style={{ "--load": `${30 + Math.round((w.count / maxCount) * 70)}%` } as React.CSSProperties} />
                  <span className={`${styles.loadText} ${heavy ? styles.loadTextHeavy : ""}`}>{loadText(w)}</span>
                </div>
              );
            })}
          </div>
        </div>
        <div className={styles.lanes}>
          {lanes.map((l) => (
            <div key={l.id} className={styles.lane}
              style={{ "--course": l.color, "--rows": Math.max(1, ...l.items.map((i) => i.row + 1)) } as React.CSSProperties}>
              <span className={styles.laneLabel}><Swatch color={l.color} />{l.label}</span>
              <ul className={styles.track} aria-label={l.label}>
                {l.items.map((it) => {
                  const mark = it.kind === "Exam" ? styles.markExam : it.kind === "Quiz" ? styles.markQuiz : "";
                  const name = `${it.title}, ${it.kind}, ${shortDate(it.day)}`;
                  return (
                    <li key={it.id} className={`${styles.mark} ${mark} ${it.row < 0 ? styles.markCrowded : ""}`}
                      style={{ "--pos": `${(timelinePos(it.day, start, weeks) * 100).toFixed(2)}%`, "--row": Math.max(0, it.row) } as React.CSSProperties}>
                      <button type="button" className={styles.markBtn} onClick={(e) => onOpen(it, e.currentTarget)}
                        aria-label={name} title={name} data-testid={`calendar-mark-${it.id}`}>
                        <span aria-hidden className={styles.glyph} />
                        <span className={styles.markText} aria-hidden>
                          {it.title}
                          <span className={styles.markDate}>{shortDate(it.day)}</span>
                        </span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            </div>
          ))}
          {todayPos >= 0 && todayPos <= 1 && (
            <>
              <span aria-hidden className={styles.todayLine} style={{ "--today": todayPos } as React.CSSProperties} />
              <span className={styles.todayTag} style={{ "--today": todayPos } as React.CSSProperties}>{VIEWS_COPY.today}</span>
            </>
          )}
        </div>
      </section>
    </div>
  );
}

export function SemesterKey() {
  return (
    <section aria-labelledby="calendar-key-h" className={styles.card}>
      <h2 id="calendar-key-h" className={styles.cardTitle}>{VIEWS_COPY.key}</h2>
      <div className={styles.keyRow}>
        <span className={`${styles.keyItem} ${styles.markExam}`}><span aria-hidden className={styles.glyph} />{VIEWS_COPY.exam}</span>
        <span className={`${styles.keyItem} ${styles.markQuiz}`}><span aria-hidden className={styles.glyph} />{VIEWS_COPY.quiz}</span>
        <span className={styles.keyItem}><span aria-hidden className={styles.glyph} />{VIEWS_COPY.homework}</span>
      </div>
      <p className={styles.cardText}>{VIEWS_COPY.keyNote}</p>
    </section>
  );
}
