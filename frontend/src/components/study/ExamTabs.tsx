"use client";
/**
 * The exam row: a tab per exam and quiz, "+" to add one, and the bell that
 * lists every upcoming deadline (homework included) and opens the dates editor.
 *
 * The row itself is not animated (only the tab list is, re-keyed on the
 * course): an animated ancestor would trap the deadlines pop-up and its
 * click-away layer inside the row.
 */
import React from "react";
import { INHERIT_FONT } from "@/lib/inheritFont";
import { Icon } from "../Icon";
import { DISPLAY, ELLIPSIS, POPOVER } from "./hubUi";
import s from "./StudyHub.module.css";
import { countdown, countFg, daysTo, fmtDow, type AssessType, type Assessment } from "./studyModel";

const TYPE_DOT: Record<AssessType, string> = { Exam: "var(--err)", Quiz: "#6A3E68", Homework: "var(--info)" };

const TAB: React.CSSProperties = { display: "flex", flexDirection: "column", alignItems: "flex-start", gap: 0, flexShrink: 0, padding: "0 0 8px", border: 0, background: "transparent", ...INHERIT_FONT, textAlign: "left", cursor: "pointer" };
const ICON_BUTTON: React.CSSProperties = { width: 36, height: 36, display: "flex", alignItems: "center", justifyContent: "center", border: 0, borderRadius: "var(--r-sm)", background: "transparent", color: "var(--text-dim)", cursor: "pointer", position: "relative" };
const BADGE: React.CSSProperties = { position: "absolute", top: 2, right: 1, minWidth: 16, height: 16, padding: "0 4px", boxSizing: "border-box", borderRadius: 8, background: "var(--err)", color: "#FFFFFF", fontSize: "var(--fs-2xs)", fontWeight: 600, display: "flex", alignItems: "center", justifyContent: "center", boxShadow: "0 0 0 2px var(--bg)" };

function ExamTab({ exam, on, today, onSelect }: { exam: Assessment; on: boolean; today: Date; onSelect: () => void }) {
  return (
    <button role="tab" aria-selected={on} className={on ? undefined : s.hoverTab} onClick={onSelect}
      style={{ ...TAB, borderBottom: `2px solid ${on ? "var(--brand-forest)" : "transparent"}` }}>
      <span style={{ fontSize: "var(--fs-base)", fontWeight: 600, color: on ? "var(--text)" : "var(--text-muted)", whiteSpace: "nowrap" }}>{exam.title}</span>
      <span style={{ fontSize: "var(--fs-sm)", color: "var(--text-muted)", whiteSpace: "nowrap" }}>{fmtDow(exam.iso, today)}</span>
    </button>
  );
}

function DeadlineRow({ item, today, onPick }: { item: Assessment; today: Date; onPick: () => void }) {
  const n = daysTo(item.iso, today);
  return (
    <button className={s.hoverOption} onClick={onPick}
      style={{ display: "flex", alignItems: "center", gap: 10, padding: 8, border: 0, borderRadius: "var(--r-sm)", background: "transparent", ...INHERIT_FONT, textAlign: "left", cursor: "pointer" }}>
      <span style={{ width: 8, height: 8, borderRadius: "50%", background: TYPE_DOT[item.type], flexShrink: 0 }} />
      <span style={{ flex: 1, minWidth: 0 }}>
        <span style={{ display: "block", fontSize: "var(--fs-md)", fontWeight: 600, ...ELLIPSIS }}>{item.title}</span>
        <span style={{ display: "block", fontSize: "var(--fs-sm)", color: "var(--text-muted)" }}>{item.type} · {fmtDow(item.iso)}</span>
      </span>
      <span style={{ fontSize: "var(--fs-sm)", fontWeight: 600, color: countFg(n), whiteSpace: "nowrap" }}>{countdown(n)}</span>
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
      <div onClick={onClose} style={{ position: "fixed", inset: 0, zIndex: 30 }} />
      <div role="dialog" aria-label="Upcoming deadlines" className={s.pop} style={{ position: "absolute", right: 0, top: 44, zIndex: 31, width: 320, maxWidth: "calc(100vw - 32px)", ...POPOVER, padding: 6, display: "flex", flexDirection: "column" }}>
        <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", padding: "6px 8px 8px" }}>
          <span style={{ fontFamily: DISPLAY, fontSize: "var(--fs-lg)", fontWeight: 600 }}>Upcoming Deadlines</span>
          <span style={{ fontSize: "var(--fs-sm)", color: "var(--text-muted)" }}>{courseLabel}</span>
        </div>
        {upcoming.length === 0 && <div style={{ padding: "4px 8px 10px", fontSize: "var(--fs-md)", color: "var(--text-muted)" }}>Nothing due for this course.</div>}
        {upcoming.map(item => <DeadlineRow key={item.id} item={item} today={today} onPick={() => onPick(item)} />)}
        <button onClick={onManage} style={{ marginTop: 4, padding: 8, border: 0, borderTop: "1px solid var(--border)", borderRadius: "0 0 8px 8px", background: "transparent", color: "var(--brand-forest)", ...INHERIT_FONT, fontSize: "var(--fs-md)", fontWeight: 600, cursor: "pointer" }}>Manage Dates</button>
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
  return (
    <div className={s.areaTabs} style={{ display: "flex", alignItems: "center", gap: 16, borderBottom: "1px solid var(--border)", minWidth: 0 }}>
      <div key={props.courseId} className={s.paneEnter} role="tablist" aria-label="Exams" style={{ flex: "0 1 auto", minWidth: 0, alignSelf: "stretch", display: "flex", gap: 28, overflowX: "auto", overflowY: "hidden" }}>
        {exams.map(e => <ExamTab key={e.id} exam={e} on={e.id === exam?.id} today={today} onSelect={() => props.onSelectExam(e.id)} />)}
        {exams.length === 0 && (
          <button onClick={onAdd} style={{ alignSelf: "center", padding: "0 0 8px", border: 0, background: "transparent", ...INHERIT_FONT, fontSize: "var(--fs-md)", fontWeight: 600, color: "var(--brand-forest)", cursor: "pointer" }}>+ Add Exam or Deadline</button>
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
      <div style={{ display: "flex", alignItems: "center", gap: 2, flexShrink: 0, marginLeft: "auto", paddingBottom: 6 }}>
        <div style={{ position: "relative" }}>
          <button className={s.hoverIcon} onClick={() => onBell(!bellOpen)} aria-label={`Upcoming deadlines, ${soon} this week`} aria-expanded={bellOpen} title="Upcoming deadlines"
            style={{ ...ICON_BUTTON, background: bellOpen ? "var(--bg-soft)" : "transparent" }}>
            <Icon name="nofitication" size={18} />
            {soon > 0 && <span style={BADGE}>{soon}</span>}
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
