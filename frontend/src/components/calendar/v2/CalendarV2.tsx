"use client";
// The redesigned calendar (behind `calendar_v2`; design: the Claude Design
// boards in calendar/v2/__fixtures__). screens/Calendar.tsx keeps the data,
// the Google connection and the syllabus upload, and hands them in; this is
// the page: Agenda (the default), Month, Week and Semester views, a course
// filter, an opened item, and an empty state for a calendar with nothing on it.
import React from "react";
import { useFlag } from "@/context/FlagsContext";
import { LEARNING_LOOP_FLAG } from "@/lib/learningLoopFlag";
import { useUser } from "@/context/UserContext";
import type { Assignment, EnrolledCourse } from "@/lib/api";
import { studyGuideHref } from "@/lib/toolHrefs";
import { TopBar } from "../../TopBar";
import { Toggle } from "@/components/ui";
import {
  addDays, agendaOf, busiestWeek, coursesOf, daysBetween, monthCells, monthTitle, rangeText,
  semesterLanes, semesterStart, shortDate, startOfWeek, toItems, undatedOf, weekCells, weekLoads, weekdayShort, WEEKDAYS,
  type CalItem,
} from "./calendarModel";
import { AgendaView, KindKey, MonthView, SemesterView, Swatch, WeekView } from "./CalendarViews";
import { ItemPanel } from "./ItemPanel";
import { useExamReadiness } from "./useExamReadiness";
import styles from "./CalendarV2.module.css";

export const CALENDAR_COPY = {
  title: "Calendar",
  views: { agenda: "Agenda", month: "Month", week: "Week", semester: "Semester" },
  viewLabel: "View",
  importSyllabus: "Import syllabus",
  more: "More",
  addDate: "Add a date",
  exportCsv: "Export as CSV",
  connectGoogle: "Connect Google Calendar",
  syncGoogle: "Sync to Google Calendar",
  viewGoogle: "View Google events",
  disconnectGoogle: "Disconnect Google Calendar",
  confirmDisconnect: "Click again to disconnect",
  allCourses: "All courses",
  coursesShown: "Courses shown",
  someCourses: (shown: number, total: number) => `${shown} of ${total} courses`,
  prev: { month: "Previous month", week: "Previous week", semester: "Earlier weeks" },
  next: { month: "Next month", week: "Next week", semester: "Later weeks" },
  today: "Today",
  busiest: (range: string) => `Busiest week: ${range}`,
  busiestText: (count: number, exams: number) =>
    `${count} due${exams ? `, ${exams === 1 ? "1 of them an exam" : `${exams} of them exams`}` : ""}.`,
  prepareFor: (title: string) => `Prepare for ${title}`,
  google: "Google Calendar",
  googleOff: "See your classes beside these dates.",
  googleOn: "Connected.",
  connect: "Connect",
  sync: "Sync",
  emptyTitle: "Add your semester's dates",
  emptyText: "Import a syllabus and Sapling finds its exams, quizzes and homework. You can fix any date afterwards.",
  emptySteps: [
    ["Upload the syllabus", "A PDF, Word or PowerPoint file from any of your courses."],
    ["Check what we found", "Fix a date, remove one, add one we missed."],
    ["See it all here", "Exams, quizzes and homework, soonest first."],
  ],
  emptyImport: "Import a syllabus",
  emptyAdd: "Add a date yourself",
  emptyGoogle: "Or connect Google Calendar",
  thisWeek: "This week",
} as const;

type View = keyof typeof CALENDAR_COPY.views;
const SEMESTER_WEEKS = 8;

export interface CalendarV2Props {
  assignments: Assignment[];
  courses: EnrolledCourse[];
  /** "now" (lib/testMode in the screen). */
  now: Date;
  googleConnected: boolean;
  importingGoogle: boolean;
  disconnectArmed: boolean;
  onImportSyllabus: () => void;
  onConnectGoogle: () => void;
  onSyncGoogle: () => void;
  onViewGoogleEvents: () => void;
  onDisconnectGoogle: () => void;
  onExportCsv: () => void;
  onReload: () => void;
}

const CHEVRON = { left: "M10 3.5 5.5 8l4.5 4.5", right: "M6 3.5 10.5 8 6 12.5", down: "M3.5 6 8 10.5 12.5 6" } as const;

function Chevron({ dir }: { dir: keyof typeof CHEVRON }) {
  return (
    <svg aria-hidden width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">
      <path d={CHEVRON[dir]} />
    </svg>
  );
}

/** A popover's open state: a click outside closes it, and Escape closes it
 *  and hands focus back to the button that opened it. */
function usePopover() {
  const [open, setOpen] = React.useState(false);
  const ref = React.useRef<HTMLDivElement>(null);
  const button = React.useRef<HTMLButtonElement>(null);
  React.useEffect(() => {
    if (!open) return;
    const off = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) setOpen(false); };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") { setOpen(false); button.current?.focus(); } };
    document.addEventListener("mousedown", off);
    document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("mousedown", off); document.removeEventListener("keydown", esc); };
  }, [open]);
  return { open, setOpen, ref, button };
}

function MoreMenu(p: Pick<CalendarV2Props, "googleConnected" | "importingGoogle" | "disconnectArmed" | "onConnectGoogle" | "onSyncGoogle" | "onViewGoogleEvents" | "onDisconnectGoogle" | "onExportCsv"> & { onAdd: (from: HTMLElement | null) => void }) {
  const { open, setOpen, ref, button } = usePopover();
  // Closing the menu removes the item just used: focus goes back to More
  // (Add a date then moves it on into the panel it opens).
  const run = (fn: () => void, keepOpen = false) => () => { fn(); if (!keepOpen) { setOpen(false); button.current?.focus(); } };
  return (
    <div className={styles.more} ref={ref}>
      <button ref={button} type="button" className={styles.iconBtn} aria-label={CALENDAR_COPY.more} aria-expanded={open}
        aria-controls="calendar-more-menu" onClick={() => setOpen((o) => !o)} data-testid="calendar-more">
        <svg aria-hidden width="16" height="16" viewBox="0 0 16 16" fill="currentColor"><circle cx="3.5" cy="8" r="1.4" /><circle cx="8" cy="8" r="1.4" /><circle cx="12.5" cy="8" r="1.4" /></svg>
      </button>
      {open && (
        <div id="calendar-more-menu" className={styles.menu} data-testid="calendar-more-menu">
          <button type="button" className={styles.menuItem} onClick={() => { p.onAdd(button.current); setOpen(false); }} data-testid="calendar-add-date">{CALENDAR_COPY.addDate}</button>
          <button type="button" className={styles.menuItem} onClick={run(p.onExportCsv)}>{CALENDAR_COPY.exportCsv}</button>
          {p.googleConnected ? (
            <>
              <button type="button" className={styles.menuItem} onClick={run(p.onSyncGoogle)}>{CALENDAR_COPY.syncGoogle}</button>
              <button type="button" className={styles.menuItem} disabled={p.importingGoogle} onClick={run(p.onViewGoogleEvents)}>{CALENDAR_COPY.viewGoogle}</button>
              <button type="button" className={styles.menuItem} onClick={run(p.onDisconnectGoogle, true)}>
                {p.disconnectArmed ? CALENDAR_COPY.confirmDisconnect : CALENDAR_COPY.disconnectGoogle}
              </button>
            </>
          ) : (
            <button type="button" className={styles.menuItem} onClick={run(p.onConnectGoogle)}>{CALENDAR_COPY.connectGoogle}</button>
          )}
        </div>
      )}
    </div>
  );
}

function CourseFilter({ courses, hidden, onToggle }: {
  courses: ReturnType<typeof coursesOf>; hidden: ReadonlySet<string>; onToggle: (id: string | null) => void;
}) {
  const { open, setOpen, ref, button } = usePopover();
  const shown = courses.filter((c) => !hidden.has(c.id));
  const label = shown.length === courses.length ? CALENDAR_COPY.allCourses
    : shown.length === 1 ? shown[0].label : CALENDAR_COPY.someCourses(shown.length, courses.length);
  return (
    <div className={styles.more} ref={ref}>
      <button ref={button} type="button" className={styles.filterBtn} aria-expanded={open} aria-controls="calendar-courses-menu"
        onClick={() => setOpen((o) => !o)} data-testid="calendar-courses">
        {shown.length === 1 && courses.length > 1 && <Swatch color={shown[0].color} />}
        {label}
        <Chevron dir="down" />
      </button>
      {open && (
        <div id="calendar-courses-menu" className={styles.menu} role="group" aria-label={CALENDAR_COPY.coursesShown} data-testid="calendar-courses-menu">
          <button type="button" className={styles.menuItem} aria-pressed={hidden.size === 0}
            onClick={() => onToggle(null)} data-testid="calendar-course-all">{CALENDAR_COPY.allCourses}</button>
          {courses.map((c) => (
            <label key={c.id} className={styles.menuCheck}>
              <input type="checkbox" checked={!hidden.has(c.id)} onChange={() => onToggle(c.id)} data-testid={`calendar-course-${c.id}`} />
              <Swatch color={c.color} />{c.label}
            </label>
          ))}
        </div>
      )}
    </div>
  );
}

function MiniMonth({ today, items, onPick }: { today: Date; items: CalItem[]; onPick: (d: Date) => void }) {
  const cells = monthCells(today, items, today);
  return (
    <section aria-labelledby="calendar-mini-h" className={`${styles.card} ${styles.miniCard}`} data-testid="calendar-mini">
      <h2 id="calendar-mini-h" className={styles.cardTitle}>{monthTitle(today)}</h2>
      <div className={styles.mini}>
        {WEEKDAYS.map((d) => <span key={d} className={styles.miniDow} aria-hidden>{d.slice(0, 1)}</span>)}
        {cells.map((c) => (
          <button key={c.iso} type="button" onClick={() => onPick(c.day)}
            className={`${styles.miniDay} ${c.inMonth ? "" : styles.miniOut} ${c.today ? styles.miniToday : ""}`}
            aria-label={`${weekdayShort(c.day)} ${shortDate(c.day)}${c.items.length ? `, ${c.items.length} due` : ""}`}>
            <span className={styles.miniNum}>{c.day.getDate()}</span>
            <span className={styles.dots} aria-hidden>
              {c.items.slice(0, 3).map((it) => <i key={it.id} style={{ "--course": it.color } as React.CSSProperties} />)}
            </span>
          </button>
        ))}
      </div>
    </section>
  );
}

function BusiestCard({ items, today, prepareHref }: { items: CalItem[]; today: Date; prepareHref: (i: CalItem) => string | null }) {
  const busy = busiestWeek(items, today);
  if (!busy) return null;
  const exam = busy.items.find((i) => i.kind === "Exam");
  const href = exam ? prepareHref(exam) : null;
  return (
    <section aria-labelledby="calendar-busy-h" className={`${styles.card} ${styles.cardWarn}`} data-testid="calendar-busiest">
      <h2 id="calendar-busy-h" className={styles.cardTitle}>{CALENDAR_COPY.busiest(busy.range)}</h2>
      <p className={styles.cardText}>{CALENDAR_COPY.busiestText(busy.count, busy.exams)}</p>
      {exam && href && <a href={href} className={styles.textBtn}>{CALENDAR_COPY.prepareFor(`${exam.course} ${exam.title}`)}</a>}
    </section>
  );
}

function GoogleCard({ connected, onConnect, onSync }: { connected: boolean; onConnect: () => void; onSync: () => void }) {
  return (
    <section aria-labelledby="calendar-google-h" className={`${styles.card} ${styles.cardDashed}`} data-testid="calendar-google-card">
      <h2 id="calendar-google-h" className={styles.cardTitle}>{CALENDAR_COPY.google}</h2>
      <p className={styles.cardText}>{connected ? CALENDAR_COPY.googleOn : CALENDAR_COPY.googleOff}</p>
      <button type="button" className="btn" onClick={connected ? onSync : onConnect}>{connected ? CALENDAR_COPY.sync : CALENDAR_COPY.connect}</button>
    </section>
  );
}

function WeekStrip({ today, items, onPick }: { today: Date; items: CalItem[]; onPick: (d: Date) => void }) {
  const cells = weekCells(today, items, today);
  return (
    <div className={styles.weekStrip} role="group" aria-label={CALENDAR_COPY.thisWeek}>
      {cells.map((c) => (
        <button key={c.iso} type="button" className={`${styles.stripDay} ${c.today ? styles.stripToday : ""}`}
          aria-current={c.today ? "date" : undefined} onClick={() => onPick(c.day)}
          aria-label={`${weekdayShort(c.day)} ${shortDate(c.day)}${c.items.length ? `, ${c.items.length} due` : ""}`}>
          {weekdayShort(c.day).slice(0, 1)}<strong>{c.day.getDate()}</strong>
          <span className={styles.dots} aria-hidden>
            {c.items.slice(0, 2).map((it) => <i key={it.id} style={{ "--course": it.color } as React.CSSProperties} />)}
          </span>
        </button>
      ))}
    </div>
  );
}

function EmptyCalendar({ onImport, onAdd, onConnect, googleConnected }: { onImport: () => void; onAdd: (from: HTMLElement) => void; onConnect: () => void; googleConnected: boolean }) {
  return (
    <section aria-labelledby="calendar-empty-h" className={styles.empty} data-testid="calendar-empty">
      <div className={styles.form}>
        <h2 id="calendar-empty-h" className={styles.emptyTitle}>{CALENDAR_COPY.emptyTitle}</h2>
        <p className={styles.cardText}>{CALENDAR_COPY.emptyText}</p>
      </div>
      <ol className={styles.steps}>
        {CALENDAR_COPY.emptySteps.map(([t, d], i) => (
          <li key={t} className={styles.step}><span className={styles.stepNum} aria-hidden>{i + 1}</span><strong>{t}</strong>{d}</li>
        ))}
      </ol>
      <div className={styles.emptyActions}>
        <button type="button" className="btn btn--primary" onClick={onImport} data-testid="calendar-empty-import">{CALENDAR_COPY.emptyImport}</button>
        <button type="button" className="btn" onClick={(e) => onAdd(e.currentTarget)} data-testid="calendar-empty-add">{CALENDAR_COPY.emptyAdd}</button>
        {!googleConnected && <button type="button" className={styles.textBtn} onClick={onConnect}>{CALENDAR_COPY.emptyGoogle}</button>}
      </div>
    </section>
  );
}

/** The opened item, held by id (null: a new date) so the panel shows it as
 *  reloaded after a save, and closed when a reload no longer has it. Closing
 *  hands focus back to the control that opened it, or to More if that is gone. */
function useOpenItem(all: CalItem[], undated: CalItem[]) {
  const [open, setOpen] = React.useState<{ id: string | null } | null>(null);
  const opener = React.useRef<HTMLElement | null>(null);
  const item = open?.id ? all.find((i) => i.id === open.id) ?? undated.find((i) => i.id === open.id) ?? null : null;
  const gone = !!open?.id && !item;
  React.useEffect(() => { if (gone) setOpen(null); }, [gone]);
  const openItem = (it: CalItem | null, from?: HTMLElement | null) => { opener.current = from ?? null; setOpen({ id: it?.id ?? null }); };
  const closeItem = () => {
    setOpen(null);
    requestAnimationFrame(() => {
      const back = opener.current?.isConnected ? opener.current : document.querySelector<HTMLElement>('[data-testid="calendar-more"]');
      back?.focus();
    });
  };
  return { isOpen: open !== null && !gone, item, openItem, closeItem };
}

function usePeriod(view: View, today: Date) {
  const [cursor, setCursorState] = React.useState(today);
  // which way the last move went, so the new period slides in from that side
  const [dir, setDir] = React.useState<1 | -1 | 0>(0);
  const step = (d: 1 | -1) => {
    setDir(d);
    setCursorState((c) => {
      if (view === "month") return new Date(c.getFullYear(), c.getMonth() + d, 1);
      return addDays(c, d * (view === "semester" ? 28 : 7));
    });
  };
  const setCursor = (c: Date) => { setDir(0); setCursorState(c); };
  return { cursor, setCursor, step, dir };
}

function periodTitle(view: View, cursor: Date): string {
  if (view === "month") return monthTitle(cursor);
  if (view === "week") { const s = startOfWeek(cursor); return rangeText(s, addDays(s, 6)); }
  const s = semesterStart(cursor);
  return rangeText(s, addDays(s, SEMESTER_WEEKS * 7 - 1));
}

export function CalendarV2(props: CalendarV2Props) {
  const { userId } = useUser();
  const today = React.useMemo(() => new Date(props.now.getFullYear(), props.now.getMonth(), props.now.getDate()), [props.now]);
  const [view, setView] = React.useState<View>("agenda");
  const period = usePeriod(view, today);
  const [hidden, setHidden] = React.useState<ReadonlySet<string>>(new Set());
  // `milestones` is a loop flag, and /api/flags does not apply the loop's gate:
  // the calendar (outside the loop) checks the loop itself.
  const loopOn = useFlag(LEARNING_LOOP_FLAG) === "on";
  const milestones = useFlag("milestones") === "on" && loopOn;
  const tutorShown = useFlag("hide_tutor") !== "on";
  const studyShown = useFlag("hide_study") !== "on";

  const all = React.useMemo(() => toItems(props.assignments, props.courses), [props.assignments, props.courses]);
  const undated = React.useMemo(() => undatedOf(props.assignments, props.courses), [props.assignments, props.courses]);
  const { isOpen, item: openItemNow, openItem, closeItem } = useOpenItem(all, undated);
  const items = React.useMemo(() => all.filter((i) => !hidden.has(i.courseId ?? "none")), [all, hidden]);
  const upcomingExams = React.useMemo(() => all.filter((i) => i.kind === "Exam" && daysBetween(today, i.day) >= 0), [all, today]);
  const readiness = useExamReadiness(upcomingExams, props.courses, milestones);
  const prepareHref = (i: CalItem) => (milestones && tutorShown && i.courseId
    ? `/learn?course=${encodeURIComponent(i.courseId)}&milestone=${encodeURIComponent(i.id)}` : null);

  const toggleCourse = (id: string | null) => setHidden((h) => {
    if (id === null) return new Set();
    const next = new Set(h);
    if (next.has(id)) next.delete(id); else next.add(id);
    return next;
  });
  const pickDay = (d: Date) => { period.setCursor(d); setView("week"); };

  const agenda = agendaOf(items, today);
  const semStart = semesterStart(period.cursor);
  const title = periodTitle(view, period.cursor);
  const itemProps = { today, readiness, prepareHref, onOpen: (i: CalItem, el: HTMLElement) => openItem(i, el) };

  const actions = (
    <>
      <span id="calendar-view-label" className={styles.srOnly}>{CALENDAR_COPY.viewLabel}</span>
      <Toggle options={(Object.keys(CALENDAR_COPY.views) as View[]).map((v) => ({ value: v, label: CALENDAR_COPY.views[v] }))}
        value={view} onChange={setView} size="sm" testid="calendar-view" labelledBy="calendar-view-label" />
      {all.length > 0 && <CourseFilter courses={coursesOf(all)} hidden={hidden} onToggle={toggleCourse} />}
      <button type="button" className="btn btn--sm btn--primary" onClick={props.onImportSyllabus} data-testid="calendar-import-syllabus">
        {CALENDAR_COPY.importSyllabus}
      </button>
      <MoreMenu {...props} onAdd={(from) => openItem(null, from)} />
    </>
  );

  return (
    <>
      {/* While an item is open the calendar behind it is inert: the panel is modal. */}
      <div className={styles.shell} inert={isOpen} data-testid="calendar-shell">
      <TopBar title={CALENDAR_COPY.title} actions={actions} />
      <div className={styles.page} data-testid="calendar-v2" data-view={view}>
        {all.length === 0 && undated.length === 0 ? (
          <EmptyCalendar onImport={props.onImportSyllabus} onAdd={(from) => openItem(null, from)} onConnect={props.onConnectGoogle} googleConnected={props.googleConnected} />
        ) : (
          <>
            {view !== "agenda" && (
              <div className={styles.toolbar}>
                <div className={styles.period}>
                  <h2 className={styles.periodTitle} aria-live="polite" data-testid="calendar-period">{title}</h2>
                  <div className={styles.stepper}>
                    <button type="button" className={styles.iconBtn} aria-label={CALENDAR_COPY.prev[view]} onClick={() => period.step(-1)} data-testid="calendar-prev"><Chevron dir="left" /></button>
                    <button type="button" className="btn btn--sm" onClick={() => period.setCursor(today)} data-testid="calendar-today">{CALENDAR_COPY.today}</button>
                    <button type="button" className={styles.iconBtn} aria-label={CALENDAR_COPY.next[view]} onClick={() => period.step(1)} data-testid="calendar-next"><Chevron dir="right" /></button>
                  </div>
                </div>
                <div className={styles.toolbarEnd}><KindKey /></div>
              </div>
            )}

            <div key={view === "agenda" ? view : `${view}:${title}`} className={styles.viewEnter}
              style={{ "--enter-x": `${period.dir * 12}px` } as React.CSSProperties}>
              {view === "agenda" && (
                <>
                  <WeekStrip today={today} items={items} onPick={pickDay} />
                  <div className={styles.agendaLayout}>
                    <AgendaView earlier={agenda.earlier} groups={agenda.groups} undated={undated} {...itemProps} />
                    <aside className={styles.rail} aria-label="At a glance">
                      <MiniMonth today={today} items={items} onPick={pickDay} />
                      <BusiestCard items={items} today={today} prepareHref={prepareHref} />
                      <GoogleCard connected={props.googleConnected} onConnect={props.onConnectGoogle} onSync={props.onSyncGoogle} />
                    </aside>
                  </div>
                </>
              )}
              {view === "month" && (
                <MonthView cells={monthCells(period.cursor, items, today)} today={today} onOpen={itemProps.onOpen} onMore={pickDay} />
              )}
              {view === "week" && <WeekView cells={weekCells(period.cursor, items, today)} today={today} onOpen={itemProps.onOpen} />}
              {view === "semester" && (
                <>
                  <SemesterView weeks={SEMESTER_WEEKS} loads={weekLoads(semStart, SEMESTER_WEEKS, items)}
                    lanes={semesterLanes(items, semStart, SEMESTER_WEEKS)} today={today} heavyStart={busiestWeek(items, today)?.start ?? null} onOpen={itemProps.onOpen} />
                  <BusiestCard items={items} today={today} prepareHref={prepareHref} />
                </>
              )}
            </div>
          </>
        )}
      </div>
      </div>
      {isOpen && (
        <ItemPanel item={openItemNow} userId={userId} courses={props.courses} today={today}
          readiness={openItemNow ? readiness.get(openItemNow.id) ?? null : null}
          prepareHref={openItemNow && !openItemNow.undated ? prepareHref(openItemNow) : null}
          studyHref={openItemNow && studyShown && openItemNow.courseId ? studyGuideHref({ course: openItemNow.courseId }) : null}
          googleConnected={props.googleConnected} onClose={closeItem}
          onChanged={(closed) => { props.onReload(); if (closed) closeItem(); }} />
      )}
    </>
  );
}
