"use client";
/**
 * Exams and Deadlines: the course's dated work as editable rows (type, name,
 * date), written through the calendar endpoints on save. Opened by the "+"
 * beside the exam tabs (on a fresh row, cursor in its Name field) and by the
 * bell's "Manage Dates".
 */
import React from "react";
import type { EnrolledCourse } from "@/lib/api";
import { INHERIT_FONT } from "@/lib/inheritFont";
import type { Draft } from "./hubModel";
import s from "./StudyHub.module.css";
import { StudyModal } from "./StudyModal";
import type { AssessType } from "./studyModel";
import type { DatesEditor } from "./useDatesEditor";

const COLUMNS = "140px minmax(0, 1fr) 170px 40px";
const FIELD: React.CSSProperties = { height: 38, padding: "0 10px", border: "1px solid var(--border-strong)", borderRadius: "var(--r-sm)", background: "var(--bg-input)", ...INHERIT_FONT, fontSize: "var(--fs-md)", color: "var(--text)", boxSizing: "border-box", minWidth: 0 };

function DraftRow({ draft, nameRef, onChange, onRemove }: {
  draft: Draft;
  /** Set on the row whose Name field takes focus (the newest blank one). */
  nameRef?: React.RefObject<HTMLInputElement | null>;
  onChange: (patch: Partial<Draft>) => void;
  onRemove: () => void;
}) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: COLUMNS, gap: 10, alignItems: "center" }}>
      <select value={draft.type} onChange={e => onChange({ type: e.target.value as AssessType })} aria-label="Type" style={FIELD}>
        <option value="Exam">Exam</option><option value="Quiz">Quiz</option><option value="Homework">Homework</option>
      </select>
      <input ref={nameRef} value={draft.title} onChange={e => onChange({ title: e.target.value })} placeholder="e.g. Midterm 3" aria-label="Name" style={FIELD} />
      {/* A cleared date is ignored: every row keeps the date it had. */}
      <input type="date" value={draft.iso} onChange={e => e.target.value && onChange({ iso: e.target.value })} aria-label="Date" style={FIELD} />
      <button className={s.hoverRemove} onClick={onRemove} aria-label="Remove" title="Remove"
        style={{ width: 38, height: 38, display: "flex", alignItems: "center", justifyContent: "center", border: 0, borderRadius: "var(--r-sm)", background: "transparent", color: "var(--err)", cursor: "pointer" }}>
        <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true"><path d="M2 2l8 8M10 2l-8 8" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" /></svg>
      </button>
    </div>
  );
}

/** "CS 101 · Intro to CS", or just the name for a course without a code. */
const courseTitle = (course: Pick<EnrolledCourse, "course_code" | "course_name">) =>
  course.course_code ? `${course.course_code} · ${course.course_name}` : course.course_name;

export function DatesEditorModal({ editor, drafts, course, isMobile }: {
  editor: DatesEditor;
  /** The editor's open rows (`editor.drafts`, known to be there). */
  drafts: Draft[];
  course: Pick<EnrolledCourse, "course_code" | "course_name">;
  isMobile: boolean;
}) {
  const { saving } = editor;
  const last = drafts.length - 1;
  return (
    <StudyModal open onClose={editor.close} label="Exams and deadlines" width={720} maxHeight={760} top={isMobile ? 40 : 120} gap={16} initialFocusRef={editor.newNameRef}>
      <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", gap: 12 }}>
        <span className="h-serif" style={{ fontSize: "var(--fs-2xl)" }}>Exams and Deadlines</span>
        <span style={{ fontSize: "var(--fs-sm)", color: "var(--text-muted)" }}>{courseTitle(course)}</span>
      </div>
      <div className="label-micro" style={{ display: "grid", gridTemplateColumns: COLUMNS, gap: 10 }}><span>Type</span><span>Name</span><span>Date</span><span /></div>
      {drafts.map((draft, i) => (
        <DraftRow key={draft.id} draft={draft} nameRef={draft.isNew && i === last ? editor.newNameRef : undefined}
          onChange={patch => editor.update(i, patch)} onRemove={() => editor.remove(i)} />
      ))}
      <button type="button" className="btn btn--sm" onClick={editor.addRow}
        style={{ alignSelf: "flex-start", height: 34, padding: "0 12px", borderStyle: "dashed", borderColor: "var(--border-strong)", background: "transparent", color: "var(--brand-forest)", fontSize: "var(--fs-md)", fontWeight: 600 }}>+ Add Exam or Deadline</button>
      <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, paddingTop: 14, borderTop: "1px solid var(--border)" }}>
        <button type="button" className="btn btn--ghost" onClick={editor.close} style={{ height: 40, padding: "0 16px" }}>Cancel</button>
        <button type="button" className="btn btn--primary" onClick={editor.save} disabled={saving} style={{ height: 40, padding: "0 16px", cursor: saving ? "wait" : "pointer" }}>{saving ? "Saving" : "Save Dates"}</button>
      </div>
    </StudyModal>
  );
}
