"use client";
/**
 * The Exams and Deadlines editor's state: the draft rows, and the save that
 * writes them through the calendar endpoints (delete, update, then add).
 */
import React from "react";
import { deleteAssignment, saveAssignments, updateAssignment } from "@/lib/api";
import { humanizeError } from "@/lib/errorMessage";
import { useToast } from "../ToastProvider";
import { draftsOf, newDraft, planDates, planIsEmpty, saveOutcome, type DatesPlan, type Draft, type SaveReply } from "./hubModel";
import type { Assessment } from "./studyModel";

export interface DatesEditor {
  /** The open editor's rows; null when it is closed. */
  drafts: Draft[] | null;
  saving: boolean;
  /** The newest blank row's Name field, which takes focus when it appears. */
  newNameRef: React.RefObject<HTMLInputElement | null>;
  /** An exam or quiz the last save added: its tab is selected once it loads. */
  justAdded: { title: string; iso: string } | null;
  clearJustAdded: () => void;
  /** Opens on the course's dates as they are now, `withNewRow` adds a blank one. */
  open: (withNewRow: boolean) => void;
  close: () => void;
  update: (index: number, patch: Partial<Draft>) => void;
  remove: (index: number) => void;
  addRow: () => void;
  save: () => Promise<void>;
}

/** Applies a plan in the order the calendar needs: removals, edits, then the
 *  new rows. Resolves with the calendar's answer to the new rows, if any. */
async function writeDates(plan: DatesPlan, userId: string, courseId: string): Promise<SaveReply | null> {
  for (const id of plan.remove) await deleteAssignment(id, userId);
  for (const u of plan.update) await updateAssignment(u.id, userId, u.patch);
  if (!plan.add.length) return null;
  return saveAssignments(userId, plan.add.map(a => ({ ...a, course_id: courseId })));
}

export function useDatesEditor(opts: {
  userId: string;
  courseId: string;
  /** The selected course's dated work. */
  list: Assessment[];
  today: Date;
  reload: () => Promise<void>;
  /** The course's dates changed (or may have, on a save that failed part-way):
   *  what is derived from them, the course's outline, needs reading again. */
  onWritten: (courseId: string) => void;
}): DatesEditor {
  const { userId, courseId, list, today, reload, onWritten } = opts;
  const toast = useToast();
  const [drafts, setDrafts] = React.useState<Draft[] | null>(null);
  const [saving, setSaving] = React.useState(false);
  const [justAdded, setJustAdded] = React.useState<{ title: string; iso: string } | null>(null);
  const newNameRef = React.useRef<HTMLInputElement | null>(null);
  /** What the open editor's drafts were made from. Save diffs against THIS, never
   *  the live list: a list that loads or reloads while the editor is open would
   *  otherwise read every row the drafts never saw as "removed" and delete it. */
  const opened = React.useRef<{ courseId: string; rows: Map<string, Assessment> } | null>(null);

  const open = (withNewRow: boolean) => {
    opened.current = { courseId, rows: new Map(list.map(e => [e.id, e])) };
    setJustAdded(null); // a tab an earlier save was still waiting to open
    const rows = draftsOf(list);
    setDrafts(withNewRow ? [...rows, newDraft(today, rows.length)] : rows);
  };
  const close = () => setDrafts(null);
  const update = (index: number, patch: Partial<Draft>) =>
    setDrafts(d => d && d.map((row, j) => (j === index ? { ...row, ...patch } : row)));
  const remove = (index: number) => setDrafts(d => d && d.filter((_, j) => j !== index));
  const addRow = () => {
    setDrafts(d => [...(d || []), newDraft(today, (d || []).length)]);
    requestAnimationFrame(() => newNameRef.current?.focus());
  };

  const save = async () => {
    const base = opened.current;
    if (!drafts || !base || !userId || !base.courseId || saving) return;
    const plan = planDates(drafts, base.rows);
    setSaving(true);
    try {
      const outcome = saveOutcome(plan, await writeDates(plan, userId, base.courseId));
      // Only once it is saved: a failed save must not leave a tab to jump to.
      // (A row refused as a duplicate has a twin already there, which is the
      // tab to open all the same.)
      if (plan.addedExam) setJustAdded(plan.addedExam);
      setDrafts(null);
      await reload();
      toast[outcome.saved ? "success" : "warn"](outcome.message);
    } catch (err) {
      console.error("study dates save failed", err);
      toast.error(humanizeError(err, "Couldn't save those dates."));
      await reload();
    } finally {
      setSaving(false);
      if (!planIsEmpty(plan)) onWritten(base.courseId);
    }
  };

  const clearJustAdded = React.useCallback(() => setJustAdded(null), []);
  return { drafts, saving, newNameRef, justAdded, clearJustAdded, open, close, update, remove, addRow, save };
}

/** An exam just added in the editor: select its tab once the reload brings it in. */
export function useSelectAddedExam(editor: DatesEditor, exams: Assessment[], select: (examId: string) => void) {
  const { justAdded, clearJustAdded } = editor;
  React.useEffect(() => {
    if (!justAdded) return;
    const hit = exams.find(e => e.title === justAdded.title && e.iso === justAdded.iso);
    if (!hit) return;
    clearJustAdded();
    select(hit.id);
  }, [justAdded, exams, clearJustAdded, select]);
}
