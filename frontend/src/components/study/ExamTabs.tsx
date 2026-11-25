"use client";
/**
 * The exam row: a tab per exam and quiz, "+" to add one, and the bell that
 * lists every upcoming deadline (homework included) and opens the dates editor.
 *
 * The row itself is not animated (only the tab list is, re-keyed on the
 * course): an animated ancestor would trap the deadlines pop-up and its
 * click-away layer inside the row.
 *
 * The selected tab's underline slides over from the tab that had it, on the
 * clock the rest of the hub changes on (./hubMotion.ts).
 *
 * The exams are tabs (WAI-ARIA tabs, automatic activation): a tab re-scopes
 * the page under the row to its exam, the readiness band with Up Next and the
 * roadmap (`aria-controls`). One tab is in the Tab order, the selected one;
 * the arrow keys, Home and End move along the row and select the tab they
 * land on, which only re-draws what is on the page. With no exam there are no
 * tabs, and the row holds only its "+ Add Exam or Deadline" link.
 */
import React from "react";
import { Icon } from "../Icon";
import { HUB_EASE, HUB_SWITCH_MS, HUB_WHOLE, reducedMotion } from "./hubMotion";
import { READINESS_ID, ROADMAP_ID } from "./hubUi";
import et from "./ExamTabs.module.css";
import s from "./StudyHub.module.css";
import { countdown, countFg, daysTo, fmtDow, type AssessType, type Assessment } from "./studyModel";

const TYPE_DOT: Record<AssessType, string> = { Exam: et.dotExam, Quiz: et.dotQuiz, Homework: et.dotHomework };

/* The title darkens as the line arrives, on the hub's clock (the app-wide
   reduced-motion reset collapses it). */
const TITLE_FADE = { "--tab-fade": `${HUB_SWITCH_MS}ms` } as React.CSSProperties;
/* The line grows from its left edge when it slides in (useSlidingLine). */
const TAB_LINE: React.CSSProperties = { transformOrigin: "0 50%" };

/** What every tab re-scopes. */
const TAB_PANELS = `${READINESS_ID} ${ROADMAP_ID}`;

/**
 * Where an arrow key, Home or End moves from tab `at` of `count` (the arrows
 * wrap round the row); null for any other key.
 */
export function tabStep(key: string, at: number, count: number): number | null {
  if (key === "ArrowRight") return (at + 1) % count;
  if (key === "ArrowLeft") return (at - 1 + count) % count;
  if (key === "Home") return 0;
  if (key === "End") return count - 1;
  return null;
}

/** `tabStop`: this tab is the row's one stop in the Tab order (roving tabindex). */
function ExamTab({ exam, on, tabStop, today, onSelect }: { exam: Assessment; on: boolean; tabStop: boolean; today: Date; onSelect: () => void }) {
  return (
    <button type="button" role="tab" aria-selected={on} aria-controls={TAB_PANELS} tabIndex={tabStop ? 0 : -1} data-tab={exam.id}
      className={on ? `${et.tab} ${et.tabOn}` : `${et.tab} ${s.hoverTab}`} onClick={onSelect} style={TITLE_FADE}>
      <span className={et.tabTitle}>{exam.title}</span>
      <span className={et.tabDate}>{fmtDow(exam.iso, today)}</span>
      {on && <span data-tab-line="" aria-hidden="true" className={et.tabLine} style={TAB_LINE} />}
    </button>
  );
}

/**
 * Slides the selected tab's line in from the tab that was selected before:
 * the line is already under its own tab (that is the layout), and starts the
 * animation drawn over the old one. Both tabs are measured at the change, so
 * nothing measured earlier can be out of date. Not under reduced motion.
 */
function useSlidingLine(list: React.RefObject<HTMLElement | null>, selectedId: string | null) {
  const before = React.useRef<string | null>(null);
  const running = React.useRef<Animation | null>(null);
  React.useLayoutEffect(() => {
    const was = before.current;
    before.current = selectedId;
    // A switch mid-slide drops the slide: the new line starts from the last tab's place.
    running.current?.cancel();
    running.current = null;
    if (!list.current || !was || !selectedId || was === selectedId || reducedMotion()) return;
    const tabs = [...list.current.querySelectorAll<HTMLElement>("[data-tab]")];
    const from = tabs.find(t => t.dataset.tab === was);
    const to = tabs.find(t => t.dataset.tab === selectedId);
    const line = to?.querySelector<HTMLElement>("[data-tab-line]");
    if (!from || !to || !line || !to.offsetWidth || typeof line.animate !== "function") return;
    const start = `translateX(${from.offsetLeft - to.offsetLeft}px) scaleX(${from.offsetWidth / to.offsetWidth})`;
    running.current = line.animate([{ transform: start }, { transform: "none" }], { ...HUB_WHOLE, easing: HUB_EASE });
  }, [list, selectedId]);
  React.useEffect(() => () => running.current?.cancel(), []);
}

/** The tab list's keys: an arrow, Home or End selects the tab it lands on and
 *  moves focus there (the tab that had focus leaves the Tab order with it). */
function tabKeys(exams: Assessment[], onSelectExam: (id: string) => void) {
  return (e: React.KeyboardEvent<HTMLElement>) => {
    const at = exams.findIndex(x => x.id === (e.target as HTMLElement).dataset.tab);
    const to = at < 0 ? null : tabStep(e.key, at, exams.length);
    if (to === null) return;
    e.preventDefault();
    const id = exams[to].id;
    onSelectExam(id);
    [...e.currentTarget.querySelectorAll<HTMLElement>("[data-tab]")].find(t => t.dataset.tab === id)?.focus();
  };
}

/** `index`: its place in the list, which staggers its entrance. */
function DeadlineRow({ item, index, today, onPick }: { item: Assessment; index: number; today: Date; onPick: () => void }) {
  const n = daysTo(item.iso, today);
  return (
    <button className={`${et.deadline} ${s.hoverOption}`} onClick={onPick} style={{ "--i": index } as React.CSSProperties}>
      <span className={`${et.dot} ${TYPE_DOT[item.type]}`} />
      <span className={et.deadlineText}>
        <span className={`${et.deadlineTitle} ${s.ellipsis}`}>{item.title}</span>
        <span className={et.deadlineMeta}>{item.type} · {fmtDow(item.iso)}</span>
      </span>
      <span className={et.deadlineCount} style={{ color: countFg(n) }}>{countdown(n)}</span>
    </button>
  );
}

/** The deadlines pop-up, with the layer behind it that a click closes it on. */
function DeadlinesPanel({ upcoming, courseLabel, today, onClose, onPick, onManage }: {
  upcoming: Assessment[];
  courseLabel: string;
  today: Date;
  onClose: () => void;
  onPick: (item: Assessment) => void;
  onManage: () => void;
}) {
  return (
    <>
      <div onClick={onClose} className={s.clickAway} />
      <div role="dialog" aria-label="Upcoming deadlines" className={`${s.pop} ${s.popover} ${et.panel}`}>
        <div className={et.panelHead}>
          <span className={et.panelTitle}>Upcoming Deadlines</span>
          <span className={et.panelMeta}>{courseLabel}</span>
        </div>
        {upcoming.length === 0 && <div className={et.panelEmpty}>Nothing due for this course.</div>}
        {upcoming.map((item, i) => <DeadlineRow key={item.id} item={item} index={i} today={today} onPick={() => onPick(item)} />)}
        <button onClick={onManage} className={et.manage}>Manage Dates</button>
      </div>
    </>
  );
}

export interface ExamTabsProps {
  courseId: string;
  courseLabel: string;
  /** The course's exams and quizzes, soonest first. */
  exams: Assessment[];
  /** The selected one. */
  exam: Assessment | null;
  /** Everything still ahead, homework included: the bell's list. */
  upcoming: Assessment[];
  /** How many of those are due this week: the bell's badge. */
  soon: number;
  today: Date;
  bellOpen: boolean;
  onBell: (open: boolean) => void;
  onSelectExam: (id: string) => void;
  /** A deadline picked in the bell: an exam or quiz selects its tab. */
  onPickDeadline: (item: Assessment) => void;
  /** Opens the dates editor on a new row. */
  onAdd: () => void;
  /** Opens the dates editor to change or remove a date. */
  onManage: () => void;
}

export function ExamTabs(props: ExamTabsProps) {
  const { exams, exam, soon, today, bellOpen, onBell, onAdd } = props;
  const tabs = React.useRef<HTMLDivElement | null>(null);
  useSlidingLine(tabs, exam?.id ?? null);
  // The selected tab is the row's Tab stop; the first one if none is.
  const stop = exams.some(e => e.id === exam?.id) ? exam?.id : exams[0]?.id;
  // The tab list only once there are tabs: the "+ Add" link that stands in
  // for them is no tab (axe aria-required-children), but keeps their place.
  const tablist = exams.length > 0 ? { role: "tablist", "aria-label": "Exams", onKeyDown: tabKeys(exams, props.onSelectExam) } : {};
  return (
    <div className={`${s.areaTabs} ${et.row}`}>
      <div ref={tabs} key={props.courseId} className={`${s.paneEnter} ${et.list}`} {...tablist}>
        {exams.map(e => <ExamTab key={e.id} exam={e} on={e.id === exam?.id} tabStop={e.id === stop} today={today} onSelect={() => props.onSelectExam(e.id)} />)}
        {exams.length === 0 && (
          <button onClick={onAdd} className={et.addLink}>+ Add Exam or Deadline</button>
        )}
      </div>
      {/* Add an exam right where the exams are listed: the "+" follows the
          last tab and opens the editor on a new row. (With no exams yet the
          row's "+ Add Exam or Deadline" link does the same.) */}
      {exams.length > 0 && (
        <button type="button" className={s.addExam} onClick={onAdd} aria-label="Add exam or deadline" title="Add an exam or deadline">
          <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true"><path d="M6 1.5v9M1.5 6h9" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" /></svg>
        </button>
      )}
      {/* Upcoming deadlines sit with the exams, at the end of the exam row.
          The gear that opened the dates editor is gone: "+" adds a date, and
          the bell's "Manage Dates" opens the editor to change or remove one. */}
      <div className={et.bellWrap}>
        <div className={et.bellAnchor}>
          <button className={`${et.iconButton} ${s.hoverIcon}${bellOpen ? ` ${et.iconButtonOpen}` : ""}`} onClick={() => onBell(!bellOpen)} aria-label={`Upcoming deadlines, ${soon} this week`} aria-expanded={bellOpen} title="Upcoming deadlines">
            <Icon name="nofitication" size={18} />
            {soon > 0 && <span className={et.badge}>{soon}</span>}
          </button>
          {bellOpen && (
            <DeadlinesPanel upcoming={props.upcoming} courseLabel={props.courseLabel} today={today}
              onClose={() => onBell(false)} onPick={props.onPickDeadline} onManage={props.onManage} />
          )}
        </div>
      </div>
    </div>
  );
}
