"use client";
// The redesigned calendar's four views (behind `calendar_v2`; design:
// calendar/v2/__fixtures__/*.design.html): Agenda (the default: what is due,
// soonest first), Month, Week and Semester (a grid: a row per course, a
// column per week). Every item opens the same panel (ItemPanel.tsx).
//
// An item's kind is a tint plus a mark, never colour alone: an exam is clay
// with a diamond, a quiz blue with a ring, homework plain with a dot.
import React from "react";
import {
  WEEKDAYS, plural, countdown, daysBetween, loadText, rangeText, addDays, shortDate, weekdayShort,
  type AgendaGroup, type CalItem, type DayCell, type SemesterLane, type WeekLoad,
} from "./calendarModel";
import styles from "./CalendarV2.module.css";

export const VIEWS_COPY = {
  earlier: (n: number, first: CalItem | undefined) =>
    n === 1 && first ? `Show 1 earlier date (${first.title}, ${shortDate(first.day)})` : `Show ${plural(n, "earlier date")}`,
  hideEarlier: "Hide earlier dates",
  earlierName: "Earlier",
  undatedName: "No date yet",
  setDate: "Set a date",
  nothingAhead: "Nothing else is due. Import a syllabus or add a date to fill it in.",
  more: (n: number) => `+${n} more`,
  today: "Today",
  key: "Key",
  thisWeek: "This week",
  busiest: "Busiest",
  course: "Course",
  nothingInSpan: "Nothing is due in these weeks.",
  exam: "Exam",
  quiz: "Quiz",
  homework: "Homework",
} as const;

const PILLS_SHOWN = 3;

const KIND_CLASS: Record<CalItem["kind"], string> = { Exam: styles.kExam, Quiz: styles.kQuiz, Homework: styles.kHomework };

/** An item's kind as its mark: a diamond, a ring or a dot (beside its words). */
export function KindMark({ kind }: { kind: CalItem["kind"] }) {
  return <span aria-hidden className={`${styles.mark} ${KIND_CLASS[kind]}`} />;
}

export function KindLabel({ kind }: { kind: CalItem["kind"] }) {
  return <span className={`${styles.kind} ${KIND_CLASS[kind]}`}><KindMark kind={kind} />{kind}</span>;
}

export function Swatch({ color }: { color: string }) {
  return <span aria-hidden className={styles.swatch} style={{ "--course": color } as React.CSSProperties} />;
}

export type ItemProps = {
  today: Date;
  onOpen: (item: CalItem, from: HTMLElement) => void;
};

function AgendaRow({ item, today, onOpen }: ItemProps & { item: CalItem }) {
  const days = daysBetween(today, item.day);
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
        </div>
      </div>
      <div className={styles.rowEnd}>
        <span className={`${styles.when} ${days >= 0 && days <= 2 ? styles.whenSoon : ""}`}>{countdown(item.day, today)}</span>
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

/** Assignments with no due date: each opens on the form, to be given one. */
function UndatedSection({ items, onOpen }: { items: CalItem[]; onOpen: ItemProps["onOpen"] }) {
  return (
    <section aria-labelledby="calendar-undated-h" className={styles.list} data-testid="calendar-undated">
      <div className={styles.groupHead}>
        <h2 id="calendar-undated-h" className={styles.h2}>{VIEWS_COPY.undatedName}</h2>
      </div>
      <ul className={styles.list}>
        {items.map((it) => (
          <li key={it.id} className={styles.row} data-testid={`calendar-undated-${it.id}`}>
            <div className={styles.rowMain}>
              <span className={styles.titleText}>{it.title}</span>
              <div className={styles.meta}>
                <span className={styles.course}><Swatch color={it.color} />{it.course}</span>
                <KindLabel kind={it.kind} />
              </div>
            </div>
            <div className={styles.rowEnd}>
              <button type="button" className={styles.prepare} onClick={(e) => onOpen(it, e.currentTarget)}
                aria-label={`${VIEWS_COPY.setDate} for ${it.title}`}>{VIEWS_COPY.setDate}</button>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}

export function AgendaView({ earlier, groups, undated = [], ...rest }: ItemProps & { earlier: CalItem[]; groups: AgendaGroup[]; undated?: CalItem[] }) {
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
      {undated.length > 0 && <UndatedSection items={undated} onOpen={rest.onOpen} />}
    </div>
  );
}

function Pill({ item, today, onOpen }: { item: CalItem; today: Date; onOpen: ItemProps["onOpen"] }) {
  const cls = [styles.pill, KIND_CLASS[item.kind], daysBetween(today, item.day) < 0 ? styles.pillPast : ""].join(" ");
  return (
    <button type="button" className={cls} data-testid={`calendar-pill-${item.id}`} onClick={(e) => onOpen(item, e.currentTarget)}
      aria-label={`${item.title}, ${item.course}, ${item.kind}, ${shortDate(item.day)}`}>
      <KindMark kind={item.kind} />
      <span>{item.title}</span>
      <Swatch color={item.color} />
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
      <KindLabel kind="Exam" />
      <KindLabel kind="Quiz" />
      <KindLabel kind="Homework" />
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

function SemesterChip({ item, today, onOpen }: { item: CalItem; today: Date; onOpen: ItemProps["onOpen"] }) {
  const past = daysBetween(today, item.day) < 0;
  const name = `${item.title}, ${item.course}, ${item.kind}, ${weekdayShort(item.day)} ${shortDate(item.day)}`;
  return (
    <button type="button" className={`${styles.ev} ${KIND_CLASS[item.kind]} ${past ? styles.pillPast : ""}`}
      onClick={(e) => onOpen(item, e.currentTarget)} aria-label={name} title={name} data-testid={`calendar-mark-${item.id}`}>
      <KindMark kind={item.kind} />
      <span className={styles.evText}>
        <span className={styles.evTitle}>{item.title}</span>
        <span className={styles.evDate}>{weekdayShort(item.day)} {item.day.getDate()}</span>
      </span>
    </button>
  );
}

export function SemesterView({ weeks, loads, lanes, today, heavyStart, onOpen }: {
  weeks: number; loads: WeekLoad[]; lanes: SemesterLane[]; today: Date; heavyStart: Date | null; onOpen: ItemProps["onOpen"];
}) {
  const maxCount = Math.max(1, ...loads.map((w) => w.count));
  const flags = loads.map((w) => ({
    now: daysBetween(w.start, today) >= 0 && daysBetween(w.start, today) < 7,
    heavy: !!heavyStart && w.start.getTime() === heavyStart.getTime(),
    past: daysBetween(addDays(w.start, 6), today) > 0,
  }));
  const colCls = (i: number) => [flags[i].now ? styles.colNow : "", flags[i].heavy ? styles.colHeavy : "", flags[i].past ? styles.colPast : ""].join(" ");
  return (
    <div className={styles.timelineScroll}>
      <div role="table" aria-label="Week by week" className={styles.sem} data-testid="calendar-semester"
        style={{ "--weeks": weeks } as React.CSSProperties}>
        <div role="row" className={styles.semRow}>
          <span role="columnheader" className={styles.semCorner}>{VIEWS_COPY.course}</span>
          {loads.map((w, i) => (
            <div key={w.label} role="columnheader" className={`${styles.semHead} ${colCls(i)}`} data-testid="calendar-week-load"
              aria-label={`Week of ${rangeText(w.start, addDays(w.start, 6))}: ${loadText(w)}`}>
              <span className={styles.semHeadTop}>
                <span className={styles.weekLabel}>{w.label}</span>
                {flags[i].now ? <span className={styles.tagNow}>{VIEWS_COPY.thisWeek}</span>
                  : flags[i].heavy ? <span className={styles.tagHeavy}>{VIEWS_COPY.busiest}</span> : null}
              </span>
              <span aria-hidden className={`${styles.load} ${w.count === 0 ? styles.loadEmpty : ""} ${flags[i].heavy ? styles.loadHeavy : ""}`}
                style={{ "--load": `${w.count === 0 ? 100 : 25 + Math.round((w.count / maxCount) * 75)}%` } as React.CSSProperties} />
              <span className={`${styles.loadText} ${flags[i].heavy ? styles.loadTextHeavy : ""}`}>{loadText(w)}</span>
            </div>
          ))}
        </div>
        {lanes.length === 0 ? <p className={styles.semNothing}>{VIEWS_COPY.nothingInSpan}</p> : lanes.map((l) => (
          <div key={l.id} role="row" className={styles.semRow}>
            <span role="rowheader" className={styles.semCourse}><Swatch color={l.color} />{l.label}</span>
            {l.cells.map((cell, i) => (
              <div key={i} role="cell" className={`${styles.semCell} ${colCls(i)}`}>
                {cell.map((it) => <SemesterChip key={it.id} item={it} today={today} onOpen={onOpen} />)}
              </div>
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}
