"use client";
// An item opened from the redesigned calendar (behind `calendar_v2`; design:
// calendar/v2/__fixtures__/detail.design.html): a side panel with, for an
// exam, how ready each of its concepts is and the ways to prepare; its
// details; Edit (the same form adds a new date); Add to Google Calendar when
// connected; Delete (click twice). Writes go through the calendar's routes.
import React from "react";
import {
  deleteAssignment, exportToGoogleCalendar, saveAssignments, updateAssignment,
  type EnrolledCourse,
} from "@/lib/api";
import { humanizeError } from "@/lib/errorMessage";
import { LEVEL_WORDS } from "@/lib/levels";
import { useConfirm } from "@/lib/useConfirm";
import { useScrollLock } from "@/lib/useScrollLock";
import { countdown, courseLabel, isoOf, longDate, type CalItem } from "./calendarModel";
import { KindLabel, Swatch, VIEWS_COPY } from "./CalendarViews";
import type { ExamReadiness } from "./useExamReadiness";
import styles from "./CalendarV2.module.css";

export const PANEL_COPY = {
  close: "Close",
  fromOutline: "from your topic outline",
  prepare: "Prepare in a session",
  studyGuide: "Make a study guide",
  details: "Details",
  edit: "Edit",
  date: "Date",
  type: "Type",
  course: "Course",
  notes: "Notes",
  name: "Name",
  noNotes: "None",
  save: "Save changes",
  add: "Add to calendar",
  cancel: "Cancel",
  saving: "Saving…",
  newTitle: "Add a date",
  google: "Add to Google Calendar",
  sentToGoogle: "Sent to Google Calendar",
  delete: "Delete",
  confirmDelete: "Click again to delete",
  needName: "Give it a name.",
  needDate: "Pick a date.",
} as const;

const TYPES = [["exam", "Exam"], ["quiz", "Quiz"], ["homework", "Homework"], ["project", "Project"], ["reading", "Reading"], ["other", "Other"]] as const;

type Draft = { title: string; iso: string; type: string; courseId: string; notes: string };

function draftOf(item: CalItem | null, courses: readonly EnrolledCourse[], today: Date): Draft {
  if (item) return { title: item.title, iso: item.iso, type: item.raw.assignment_type || item.kind.toLowerCase(), courseId: item.courseId ?? "", notes: item.notes };
  return { title: "", iso: isoOf(today), type: "exam", courseId: courses[0]?.course_id ?? "", notes: "" };
}

function Form({ draft, setDraft, courses, error }: {
  draft: Draft; setDraft: React.Dispatch<React.SetStateAction<Draft>>; courses: readonly EnrolledCourse[]; error: string | null;
}) {
  const set = (k: keyof Draft) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) =>
    setDraft((d) => ({ ...d, [k]: e.target.value }));
  return (
    <div className={styles.form} data-testid="calendar-panel-form">
      <label className={styles.field}>{PANEL_COPY.name}
        <input className={styles.input} value={draft.title} maxLength={200} onChange={set("title")} data-testid="calendar-field-title" />
      </label>
      <label className={styles.field}>{PANEL_COPY.date}
        <input type="date" className={styles.input} value={draft.iso} onChange={set("iso")} data-testid="calendar-field-date" />
      </label>
      <label className={styles.field}>{PANEL_COPY.type}
        <select className={styles.input} value={draft.type} onChange={set("type")} data-testid="calendar-field-type">
          {TYPES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </select>
      </label>
      <label className={styles.field}>{PANEL_COPY.course}
        <select className={styles.input} value={draft.courseId} onChange={set("courseId")} data-testid="calendar-field-course">
          {courses.map((c) => <option key={c.course_id} value={c.course_id}>{courseLabel(c)}</option>)}
        </select>
      </label>
      <label className={styles.field}>{PANEL_COPY.notes}
        <textarea className={styles.input} value={draft.notes} maxLength={2000} onChange={set("notes")} />
      </label>
      {error && <p role="alert" className={styles.formError}>{error}</p>}
    </div>
  );
}

function ReadyBox({ r, prepareHref, studyHref }: { r: ExamReadiness; prepareHref: string | null; studyHref: string | null }) {
  return (
    <section aria-labelledby="calendar-ready-h" className={styles.readyBox} data-testid="calendar-panel-readiness">
      <div className={styles.groupHead}>
        <h3 id="calendar-ready-h" className={styles.h2}>{VIEWS_COPY.ready(r)}</h3>
        <span className={styles.dim}>{PANEL_COPY.fromOutline}</span>
      </div>
      <ul className={styles.list}>
        {r.concepts.map((c) => {
          const word = LEVEL_WORDS[c.level];
          const pct = c.score == null ? 0 : Math.round(Math.max(0, Math.min(1, c.score)) * 100);
          return (
            <li key={c.id} className={styles.concept}>
              <span>{c.name}</span>
              <span className={styles.meter} role="meter" aria-label={`${c.name} skill`} aria-valuetext={word}
                aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct}>
                <i style={{ "--fill": `${pct}%` } as React.CSSProperties} />
              </span>
              <span className={styles.level}>{word}</span>
            </li>
          );
        })}
      </ul>
      {(prepareHref || studyHref) && (
        <div className={styles.actions}>
          {prepareHref && <a href={prepareHref} className="btn btn--primary" data-testid="calendar-panel-prepare">{PANEL_COPY.prepare}</a>}
          {studyHref && <a href={studyHref} className="btn" data-testid="calendar-panel-study-guide">{PANEL_COPY.studyGuide}</a>}
        </div>
      )}
    </section>
  );
}

function useSave(userId: string, item: CalItem | null, onSaved: () => void) {
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const save = async (d: Draft) => {
    if (!d.title.trim()) return setError(PANEL_COPY.needName);
    if (!d.iso) return setError(PANEL_COPY.needDate);
    setSaving(true);
    setError(null);
    const fields = { title: d.title.trim(), due_date: d.iso, assignment_type: d.type, course_id: d.courseId || undefined, notes: d.notes };
    try {
      if (item) await updateAssignment(item.id, userId, fields);
      else await saveAssignments(userId, [{ ...fields, notes: d.notes || null }]);
      onSaved();
    } catch (err) {
      setError(humanizeError(err, "Couldn't save that. Try again."));
    } finally {
      setSaving(false);
    }
  };
  return { saving, error, save };
}

export function ItemPanel({ item, userId, courses, today, readiness, prepareHref, studyHref, googleConnected, onClose, onChanged }: {
  /** The item opened; null adds a new date. */
  item: CalItem | null;
  userId: string;
  courses: readonly EnrolledCourse[];
  today: Date;
  readiness: ExamReadiness | null;
  prepareHref: string | null;
  studyHref: string | null;
  googleConnected: boolean;
  onClose: () => void;
  /** Something was written: reload the calendar (and close on a delete). */
  onChanged: (closed: boolean) => void;
}) {
  useScrollLock(true);
  const heading = React.useRef<HTMLHeadingElement>(null);
  const [editing, setEditing] = React.useState(item === null);
  const [draft, setDraft] = React.useState<Draft>(() => draftOf(item, courses, today));
  const [sent, setSent] = React.useState(false);
  const { saving, error, save } = useSave(userId, item, () => { setEditing(false); onChanged(item === null); });
  const del = useConfirm(async () => {
    if (!item) return;
    await deleteAssignment(item.id, userId);
    onChanged(true);
  });
  React.useLayoutEffect(() => { heading.current?.focus(); }, []);
  React.useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  const toGoogle = async () => {
    if (!item) return;
    await exportToGoogleCalendar(userId, [item.id]).then(() => setSent(true)).catch(() => setSent(false));
  };
  const title = item ? item.title : PANEL_COPY.newTitle;
  return (
    <>
      <div className={styles.scrim} onClick={onClose} aria-hidden />
      <section role="dialog" aria-modal="true" aria-labelledby="calendar-panel-title" className={styles.panel} data-testid="calendar-panel">
        <div className={styles.panelHead}>
          <div className={styles.rowMain}>
            {item && (
              <div className={styles.meta}>
                <span className={styles.course}><Swatch color={item.color} />{item.course}</span>
                <KindLabel kind={item.kind} />
              </div>
            )}
            <h2 id="calendar-panel-title" ref={heading} tabIndex={-1} className={styles.panelTitle}>{title}</h2>
            {item && <p className={styles.dim}>{longDate(item.day)} · <strong>{countdown(item.day, today)}</strong></p>}
          </div>
          <button type="button" className={styles.iconBtn} aria-label={PANEL_COPY.close} onClick={onClose} data-testid="calendar-panel-close">
            <svg aria-hidden width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"><path d="m3 3 8 8M11 3l-8 8" /></svg>
          </button>
        </div>

        {item && readiness && !editing && <ReadyBox r={readiness} prepareHref={prepareHref} studyHref={studyHref} />}

        {editing ? (
          <Form draft={draft} setDraft={setDraft} courses={courses} error={error} />
        ) : item && (
          <section aria-labelledby="calendar-details-h" className={styles.form}>
            <div className={styles.cardHead}>
              <h3 id="calendar-details-h" className={styles.cardTitle}>{PANEL_COPY.details}</h3>
              <button type="button" className={styles.textBtn} onClick={() => setEditing(true)} data-testid="calendar-panel-edit">{PANEL_COPY.edit}</button>
            </div>
            <dl className={styles.details}>
              <dt>{PANEL_COPY.date}</dt><dd>{longDate(item.day)}, {item.day.getFullYear()}</dd>
              <dt>{PANEL_COPY.type}</dt><dd>{item.kind}</dd>
              <dt>{PANEL_COPY.course}</dt><dd>{item.course}</dd>
              <dt>{PANEL_COPY.notes}</dt><dd>{item.notes || PANEL_COPY.noNotes}</dd>
            </dl>
          </section>
        )}

        <div className={styles.panelFoot}>
          {editing ? (
            <>
              <button type="button" className="btn btn--primary" disabled={saving} onClick={() => void save(draft)} data-testid="calendar-panel-save">
                {saving ? PANEL_COPY.saving : item ? PANEL_COPY.save : PANEL_COPY.add}
              </button>
              <button type="button" className="btn" onClick={() => (item ? setEditing(false) : onClose())}>{PANEL_COPY.cancel}</button>
            </>
          ) : (
            googleConnected && item && (
              <button type="button" className="btn" disabled={sent} onClick={() => void toGoogle()} data-testid="calendar-panel-google">
                {sent ? PANEL_COPY.sentToGoogle : PANEL_COPY.google}
              </button>
            )
          )}
          {item && (
            <button type="button" className={styles.danger} onClick={del.trigger} data-testid="calendar-panel-delete">
              {del.armed ? PANEL_COPY.confirmDelete : PANEL_COPY.delete}
            </button>
          )}
        </div>
      </section>
    </>
  );
}
