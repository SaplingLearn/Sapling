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
 */
import React from "react";
import { Icon } from "../Icon";
import { HUB_EASE, HUB_SWITCH_MS, HUB_WHOLE, reducedMotion } from "./hubMotion";
import s from "./StudyHub.module.css";
import { countdown, countFg, daysTo, fmtDow, type AssessType, type Assessment } from "./studyModel";
import { cn } from "@/lib/cn";

const TYPE_DOT: Record<AssessType, string> = { Exam: "var(--err)", Quiz: "#6A3E68", Homework: "var(--info)" };

/* The title darkens as the line arrives (the app-wide reduced-motion reset collapses it). */
const TITLE_FADE = `color ${HUB_SWITCH_MS}ms ${HUB_EASE}`;

function ExamTab({ exam, on, today, onSelect }: { exam: Assessment; on: boolean; today: Date; onSelect: () => void }) {
  return (
    <button role="tab" aria-selected={on} data-tab={exam.id} className={cn(on ? undefined : s.hoverTab, "relative flex flex-col items-start gap-0 shrink-0 pt-0 px-0 pb-2 border-0 border-b-2 border-b-transparent [background:transparent] [font-family:inherit] [font-size:inherit] [font-weight:inherit] [font-style:inherit] [line-height:inherit] text-left cursor-pointer")} onClick={onSelect}>
      <span className={cn("text-base font-semibold whitespace-nowrap", on ? "text-text" : "text-text-muted")} style={{ transition: TITLE_FADE }}>{exam.title}</span>
      <span className="text-sm text-text-muted whitespace-nowrap">{fmtDow(exam.iso, today)}</span>
      {on && <span data-tab-line="" aria-hidden="true" className="absolute left-0 right-0 -bottom-0.5 h-0.5 bg-brand-forest [transform-origin:0_50%]" />}
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

function DeadlineRow({ item, today, onPick }: { item: Assessment; today: Date; onPick: () => void }) {
  const n = daysTo(item.iso, today);
  return (
    <button className={cn(s.hoverOption, "flex items-center gap-2.5 p-2 border-0 rounded-sm [background:transparent] [font-family:inherit] [font-size:inherit] [font-weight:inherit] [font-style:inherit] [line-height:inherit] text-left cursor-pointer")} onClick={onPick}>
      <span className="w-2 h-2 rounded-[50%] shrink-0" style={{ background: TYPE_DOT[item.type] }} />
      <span className="flex-1 min-w-0">
        <span className="block text-md font-semibold whitespace-nowrap overflow-hidden text-ellipsis">{item.title}</span>
        <span className="block text-sm text-text-muted">{item.type} · {fmtDow(item.iso)}</span>
      </span>
      <span className="text-sm font-semibold whitespace-nowrap" style={{ color: countFg(n) }}>{countdown(n)}</span>
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
      <div onClick={onClose} className="fixed inset-0 z-30" />
      <div role="dialog" aria-label="Upcoming deadlines" className={cn(s.pop, "absolute right-0 top-11 z-31 w-80 max-w-[calc(100vw_-_32px)] [background:var(--bg-panel)] border border-border rounded-md shadow-lg p-1.5 flex flex-col")}>
        <div className="flex items-baseline justify-between pt-1.5 px-2 pb-2">
          <span className="font-display text-lg font-semibold">Upcoming Deadlines</span>
          <span className="text-sm text-text-muted">{courseLabel}</span>
        </div>
        {upcoming.length === 0 && <div className="pt-1 px-2 pb-2.5 text-md text-text-muted">Nothing due for this course.</div>}
        {upcoming.map(item => <DeadlineRow key={item.id} item={item} today={today} onPick={() => onPick(item)} />)}
        <button onClick={onManage} className="mt-1 p-2 border-0 border-t border-t-border [border-radius:0_0_8px_8px] bg-transparent text-brand-forest [font-family:inherit] [font-style:inherit] [line-height:inherit] text-md font-semibold cursor-pointer">Manage Dates</button>
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
  return (
    <div className={cn(s.areaTabs, "flex items-center gap-4 border-b border-b-border min-w-0")}>
      <div ref={tabs} key={props.courseId} className={cn(s.paneEnter, "flex-[0_1_auto] min-w-0 self-stretch flex gap-7 overflow-x-auto overflow-y-hidden")} role="tablist" aria-label="Exams">
        {exams.map(e => <ExamTab key={e.id} exam={e} on={e.id === exam?.id} today={today} onSelect={() => props.onSelectExam(e.id)} />)}
        {exams.length === 0 && (
          <button onClick={onAdd} className="self-center pt-0 px-0 pb-2 border-0 bg-transparent [font-family:inherit] [font-style:inherit] [line-height:inherit] text-md font-semibold text-brand-forest cursor-pointer">+ Add Exam or Deadline</button>
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
      <div className="flex items-center gap-0.5 shrink-0 ml-auto pb-1.5">
        <div className="relative">
          <button className={cn(s.hoverIcon, "w-9 h-9 flex items-center justify-center border-0 rounded-sm text-text-dim cursor-pointer relative", bellOpen ? "[background:var(--bg-soft)]" : "[background:transparent]")} onClick={() => onBell(!bellOpen)} aria-label={`Upcoming deadlines, ${soon} this week`} aria-expanded={bellOpen} title="Upcoming deadlines">
            <Icon name="nofitication" size={18} />
            {soon > 0 && <span className="absolute top-0.5 right-px min-w-4 h-4 py-0 px-1 box-border rounded-[8px] bg-err text-accent-fg text-2xs font-semibold flex items-center justify-center [box-shadow:0_0_0_2px_var(--bg)]">{soon}</span>}
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
