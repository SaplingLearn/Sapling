"use client";
// The redesigned calendar (behind `calendar_v2`; design: the Claude Design
// boards in calendar/v2/__fixtures__). screens/Calendar.tsx keeps the data,
// the Google connection and the syllabus upload, and hands them in; this is
// the page: Agenda (the default), Month, Week and Semester views, a course
// filter, an opened item, and an empty state for a calendar with nothing on it.
import React from "react";
import { useFlag } from "@/context/FlagsContext";
import { useUser } from "@/context/UserContext";
import type { Assignment, EnrolledCourse } from "@/lib/api";
import { studyGuideHref } from "@/lib/toolHrefs";
import { TopBar } from "../../TopBar";
import { Toggle } from "@/components/ui";
import {
  addDays, agendaOf, busiestWeek, coursesOf, daysBetween, longDate, monthCells, monthLine, monthTitle, rangeText,
  semesterLanes, semesterStart, shortDate, startOfWeek, toItems, weekCells, weekLine, weekLoads, weekdayShort, WEEKDAYS,
  type CalItem,
} from "./calendarModel";
import { AgendaView, KindKey, MonthView, SemesterKey, SemesterView, Swatch, WeekView } from "./CalendarViews";
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
  prev: { month: "Previous month", week: "Previous week", semester: "Earlier weeks" },
  next: { month: "Next month", week: "Next week", semester: "Later weeks" },
  today: "Today",
  semesterTitle: "Week by week",
  semesterSub: "Each course on its own line, so heavy weeks show before you reach them.",
  busiest: (range: string) => `Busiest week: ${range}`,
  busiestText: (count: number, exams: number) =>
    `${count} due${exams ? `, ${exams === 1 ? "1 of them an exam" : `${exams} of them exams`}` : ""}. Starting early leaves room for the rest.`,
  prepareFor: (title: string) => `Prepare for ${title}`,
  google: "Google Calendar",
  googleOff: "Not connected. Connect to see your classes beside these dates, or send them there.",
  googleOn: "Connected. Sync sends your dates there.",
  connect: "Connect",
  sync: "Sync",
  emptyTitle: "Add your semester's dates",
  emptyText: "Import a syllabus and Sapling finds its exams, quizzes and homework. You can fix any date afterwards, and each exam gets a countdown and a way to prepare for it.",
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

function Chevron({ dir }: { dir: "left" | "right" }) {
  return (
    <svg aria-hidden width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">
      <path d={dir === "left" ? "M10 3.5 5.5 8l4.5 4.5" : "M6 3.5 10.5 8 6 12.5"} />
    </svg>
  );
}

function MoreMenu(p: Pick<CalendarV2Props, "googleConnected" | "importingGoogle" | "disconnectArmed" | "onConnectGoogle" | "onSyncGoogle" | "onViewGoogleEvents" | "onDisconnectGoogle" | "onExportCsv"> & { onAdd: () => void }) {
  const [open, setOpen] = React.useState(false);
  const ref = React.useRef<HTMLDivElement>(null);
  React.useEffect(() => {
    if (!open) return;
    const off = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) setOpen(false); };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", off);
    document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("mousedown", off); document.removeEventListener("keydown", esc); };
  }, [open]);
  const run = (fn: () => void, keepOpen = false) => () => { fn(); if (!keepOpen) setOpen(false); };
  return (
    <div className={styles.more} ref={ref}>
      <button type="button" className={styles.iconBtn} aria-label={CALENDAR_COPY.more} aria-expanded={open}
        aria-controls="calendar-more-menu" onClick={() => setOpen((o) => !o)} data-testid="calendar-more">
        <svg aria-hidden width="16" height="16" viewBox="0 0 16 16" fill="currentColor"><circle cx="3.5" cy="8" r="1.4" /><circle cx="8" cy="8" r="1.4" /><circle cx="12.5" cy="8" r="1.4" /></svg>
      </button>
      {open && (
        <div id="calendar-more-menu" className={styles.menu} data-testid="calendar-more-menu">
          <button type="button" className={styles.menuItem} onClick={run(p.onAdd)} data-testid="calendar-add-date">{CALENDAR_COPY.addDate}</button>
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

function EmptyCalendar({ onImport, onAdd, onConnect, googleConnected }: { onImport: () => void; onAdd: () => void; onConnect: () => void; googleConnected: boolean }) {
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
        <button type="button" className="btn" onClick={onAdd} data-testid="calendar-empty-add">{CALENDAR_COPY.emptyAdd}</button>
        {!googleConnected && <button type="button" className={styles.textBtn} onClick={onConnect}>{CALENDAR_COPY.emptyGoogle}</button>}
      </div>
    </section>
  );
}

function usePeriod(view: View, today: Date) {
  const [cursor, setCursor] = React.useState(today);
  const step = (dir: 1 | -1) => setCursor((c) => {
    if (view === "month") return new Date(c.getFullYear(), c.getMonth() + dir, 1);
    return addDays(c, dir * (view === "semester" ? 28 : 7));
  });
  return { cursor, setCursor, step };
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
  const [open, setOpen] = React.useState<{ item: CalItem | null } | null>(null);
  const opener = React.useRef<HTMLElement | null>(null);
  const milestones = useFlag("milestones") === "on";
  const tutorShown = useFlag("hide_tutor") !== "on";
  const studyShown = useFlag("hide_study") !== "on";

  const all = React.useMemo(() => toItems(props.assignments, props.courses), [props.assignments, props.courses]);
  const items = React.useMemo(() => all.filter((i) => !hidden.has(i.courseId ?? "none")), [all, hidden]);
  const upcomingExams = React.useMemo(() => all.filter((i) => i.kind === "Exam" && daysBetween(today, i.day) >= 0), [all, today]);
  const readiness = useExamReadiness(upcomingExams, props.courses, milestones);
  const prepareHref = (i: CalItem) => (milestones && tutorShown && i.courseId
    ? `/learn?course=${encodeURIComponent(i.courseId)}&milestone=${encodeURIComponent(i.id)}` : null);

  const openItem = (item: CalItem | null, from?: HTMLElement | null) => { opener.current = from ?? null; setOpen({ item }); };
  const closeItem = () => { setOpen(null); requestAnimationFrame(() => opener.current?.focus()); };
  const toggleCourse = (id: string | null) => setHidden((h) => {
    if (id === null) return new Set();
    const next = new Set(h);
    if (next.has(id)) next.delete(id); else next.add(id);
    return next;
  });
  const pickDay = (d: Date) => { period.setCursor(d); setView("week"); };

  const agenda = agendaOf(items, today);
  const subtitle = view === "agenda" ? `${longDate(today)} · ${weekLine(items, today)}`
    : view === "month" ? `${monthLine(period.cursor, items)} · ${all.length} in all`
      : view === "semester" ? CALENDAR_COPY.semesterSub : `${weekLine(items, today)}`;
  const semStart = semesterStart(period.cursor);
  const courseChips = coursesOf(all);
  const itemProps = { today, readiness, prepareHref, onOpen: (i: CalItem, el: HTMLElement) => openItem(i, el) };

  const actions = (
    <>
      <span id="calendar-view-label" className={styles.srOnly}>{CALENDAR_COPY.viewLabel}</span>
      <Toggle options={(Object.keys(CALENDAR_COPY.views) as View[]).map((v) => ({ value: v, label: CALENDAR_COPY.views[v] }))}
        value={view} onChange={setView} size="sm" testid="calendar-view" labelledBy="calendar-view-label" />
      <button type="button" className="btn btn--sm btn--primary" onClick={props.onImportSyllabus} data-testid="calendar-import-syllabus">
        {CALENDAR_COPY.importSyllabus}
      </button>
      <MoreMenu {...props} onAdd={() => openItem(null)} />
    </>
  );

  return (
    <>
      <TopBar title={view === "semester" ? CALENDAR_COPY.semesterTitle : CALENDAR_COPY.title} subtitle={subtitle} actions={actions} />
      <div className={styles.page} data-testid="calendar-v2" data-view={view}>
        {all.length === 0 ? (
          <EmptyCalendar onImport={props.onImportSyllabus} onAdd={() => openItem(null)} onConnect={props.onConnectGoogle} googleConnected={props.googleConnected} />
        ) : (
          <>
            <div className={styles.toolbar}>
              {view !== "agenda" && (
                <div className={styles.period}>
                  <button type="button" className={styles.iconBtn} aria-label={CALENDAR_COPY.prev[view]} onClick={() => period.step(-1)} data-testid="calendar-prev"><Chevron dir="left" /></button>
                  <button type="button" className={styles.iconBtn} aria-label={CALENDAR_COPY.next[view]} onClick={() => period.step(1)} data-testid="calendar-next"><Chevron dir="right" /></button>
                  <h2 className={styles.periodTitle} aria-live="polite" data-testid="calendar-period">{periodTitle(view, period.cursor)}</h2>
                  <button type="button" className="btn btn--sm" onClick={() => period.setCursor(today)}>{CALENDAR_COPY.today}</button>
                </div>
              )}
              {view === "month" && <KindKey />}
              <div className={styles.chips} role="group" aria-label={CALENDAR_COPY.coursesShown}>
                <button type="button" className={`${styles.chip} ${styles.chipAll}`} aria-pressed={hidden.size === 0}
                  onClick={() => toggleCourse(null)} data-testid="calendar-course-all">{CALENDAR_COPY.allCourses}</button>
                {courseChips.map((c) => (
                  <button key={c.id} type="button" className={styles.chip} aria-pressed={!hidden.has(c.id)}
                    onClick={() => toggleCourse(c.id)} data-testid={`calendar-course-${c.id}`}>
                    <Swatch color={c.color} />{c.label}
                  </button>
                ))}
              </div>
            </div>

            {view === "agenda" && (
              <>
                <WeekStrip today={today} items={items} onPick={pickDay} />
                <div className={styles.agendaLayout}>
                  <AgendaView earlier={agenda.earlier} groups={agenda.groups} {...itemProps} />
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
                <div className={styles.belowTimeline}>
                  <BusiestCard items={items} today={today} prepareHref={prepareHref} />
                  <SemesterKey />
                </div>
              </>
            )}
          </>
        )}
      </div>
      {open && (
        <ItemPanel item={open.item} userId={userId} courses={props.courses} today={today}
          readiness={open.item ? readiness.get(open.item.id) ?? null : null}
          prepareHref={open.item ? prepareHref(open.item) : null}
          studyHref={open.item && studyShown && open.item.courseId ? studyGuideHref({ course: open.item.courseId }) : null}
          googleConnected={props.googleConnected} onClose={closeItem}
          onChanged={(closed) => { props.onReload(); if (closed) closeItem(); }} />
      )}
    </>
  );
}
