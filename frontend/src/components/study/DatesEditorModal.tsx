"use client";
/**
 * Exams and Deadlines: the course's dated work as editable rows (type, name,
 * date), written through the calendar endpoints on save. Opened by the "+"
 * beside the exam tabs (on a fresh row, cursor in its Name field) and by the
 * bell's "Manage Dates".
 */
import React from "react";
import type { EnrolledCourse } from "@/lib/api";
import type { Draft } from "./hubModel";
import s from "./StudyHub.module.css";
import { StudyModal } from "./StudyModal";
import type { AssessType } from "./studyModel";
import type { DatesEditor } from "./useDatesEditor";
import { cn } from "@/lib/cn";

function DraftRow({ draft, nameRef, onChange, onRemove }: {
  draft: Draft;
  /** Set on the row whose Name field takes focus (the newest blank one). */
  nameRef?: React.RefObject<HTMLInputElement | null>;
  onChange: (patch: Partial<Draft>) => void;
  onRemove: () => void;
}) {
  return (
    <div className="grid grid-cols-[140px_minmax(0,_1fr)_170px_40px] gap-2.5 items-center">
      <select value={draft.type} onChange={e => onChange({ type: e.target.value as AssessType })} aria-label="Type" className="h-9.5 py-0 px-2.5 border border-border-strong rounded-sm bg-bg-input [font-family:inherit] [font-weight:inherit] [font-style:inherit] [line-height:inherit] text-md text-text box-border min-w-0">
        <option value="Exam">Exam</option><option value="Quiz">Quiz</option><option value="Homework">Homework</option>
      </select>
      <input ref={nameRef} value={draft.title} onChange={e => onChange({ title: e.target.value })} placeholder="e.g. Midterm 3" aria-label="Name" className="h-9.5 py-0 px-2.5 border border-border-strong rounded-sm bg-bg-input [font-family:inherit] [font-weight:inherit] [font-style:inherit] [line-height:inherit] text-md text-text box-border min-w-0" />
      {/* A cleared date is ignored: every row keeps the date it had. */}
      <input type="date" value={draft.iso} onChange={e => e.target.value && onChange({ iso: e.target.value })} aria-label="Date" className="h-9.5 py-0 px-2.5 border border-border-strong rounded-sm bg-bg-input [font-family:inherit] [font-weight:inherit] [font-style:inherit] [line-height:inherit] text-md text-text box-border min-w-0" />
      <button className={cn(s.hoverRemove, "w-9.5 h-9.5 flex items-center justify-center border-0 rounded-sm [background:transparent] text-err cursor-pointer")} onClick={onRemove} aria-label="Remove" title="Remove">
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
      <div className="flex items-baseline justify-between gap-3">
        <span className="h-serif text-2xl">Exams and Deadlines</span>
        <span className="text-sm text-text-muted">{courseTitle(course)}</span>
      </div>
      <div className="label-micro grid grid-cols-[140px_minmax(0,_1fr)_170px_40px] gap-2.5"><span>Type</span><span>Name</span><span>Date</span><span /></div>
      {drafts.map((draft, i) => (
        <DraftRow key={draft.id} draft={draft} nameRef={draft.isNew && i === last ? editor.newNameRef : undefined}
          onChange={patch => editor.update(i, patch)} onRemove={() => editor.remove(i)} />
      ))}
      <button type="button" className="btn btn--sm self-start h-8.5 py-0 px-3 border-dashed border-border-strong bg-transparent text-brand-forest text-md font-semibold" onClick={editor.addRow}>+ Add Exam or Deadline</button>
      <div className="flex justify-end gap-2 pt-3.5 border-t border-t-border">
        <button type="button" className="btn btn--ghost h-10 py-0 px-4" onClick={editor.close}>Cancel</button>
        <button type="button" className={cn("btn btn--primary", "h-10 py-0 px-4", saving ? "cursor-wait" : "cursor-pointer")} onClick={editor.save} disabled={saving}>{saving ? "Saving" : "Save Dates"}</button>
      </div>
    </StudyModal>
  );
}
