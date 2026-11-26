"use client";
/**
 * The Library's upload flow: pick files, choose where they belong, run them,
 * and file the results.
 *
 * `useUploadQueue` owns the streaming and the per-file retry; this owns the
 * dialog around it and what happens once every file has settled — the one
 * part the prototype has no equivalent for, because its upload is instant.
 */
import React from "react";

import type { EnrolledCourse } from "@/lib/api";

import { guessCourse } from "./UploadWhereModal";
import type { Loc } from "./libraryModel";
import type { LibraryData } from "./useLibraryData";
import { rowsFor, useUploadQueue, type UploadQueue } from "./useUploadQueue";

/** `sapModalOut` runs for 160 ms; the scrim's fade is 180 ms. */
const MODAL_EXIT_MS = 180;
/** Syllabus ingestion finishes server-side a moment after the stream closes (#769). */
const SYLLABUS_REPOLL_MS = 1500;

export interface UploadDialog {
  courseId: string | null;
  folderId: string | null;
  /** The course the filenames suggest, shown above the picker. */
  suggested: string | null;
  /** The picker is done; the dialog is showing progress. */
  started: boolean;
}

export interface LibraryUpload {
  queue: UploadQueue;
  dialog: UploadDialog | null;
  closing: boolean;
  setCourseId: (id: string | null) => void;
  setFolderId: (id: string | null) => void;
  pickFiles: (files: File[]) => void;
  confirm: () => void;
  close: () => void;
  retryRow: (id: string) => void;
}

export interface LibraryUploadInput {
  userId: string;
  data: LibraryData;
  courses: EnrolledCourse[];
  /** Where the student is standing: a new upload defaults to here. */
  scopeCourseId: string | null;
  openFolderId: string | null;
  goTo: (loc: Loc) => void;
  select: (docId: string) => void;
  notifySyllabus: () => void;
}

export function useLibraryUpload(input: LibraryUploadInput): LibraryUpload {
  const {
    userId, data, courses, scopeCourseId, openFolderId, goTo, select, notifySyllabus,
  } = input;
  const queue = useUploadQueue(userId);
  const [dialog, setDialog] = React.useState<UploadDialog | null>(null);
  const [closing, setClosing] = React.useState(false);
  // One settle per run, even though `finished` stays true after it flips.
  const settled = React.useRef(false);
  const closeTimer = React.useRef<ReturnType<typeof setTimeout> | null>(null);

  React.useEffect(() => () => {
    if (closeTimer.current) clearTimeout(closeTimer.current);
  }, []);

  const pickFiles = React.useCallback((files: File[]) => {
    if (!files.length) return;
    queue.setRows(rowsFor(files));
    const suggested = guessCourse(files, courses);
    settled.current = false;
    setDialog({
      courseId: suggested ?? scopeCourseId,
      folderId: openFolderId,
      suggested,
      started: false,
    });
  }, [queue, courses, scopeCourseId, openFolderId]);

  const close = React.useCallback(() => {
    setClosing(true);
    if (closeTimer.current) clearTimeout(closeTimer.current);
    closeTimer.current = setTimeout(() => {
      setClosing(false);
      setDialog(null);
      queue.reset();
    }, MODAL_EXIT_MS);
  }, [queue]);

  const confirm = React.useCallback(() => {
    setDialog(d => {
      if (!d?.courseId) return d;
      queue.start(d.courseId);
      return { ...d, started: true };
    });
  }, [queue]);

  const setCourseId = React.useCallback((id: string | null) => {
    setDialog(d => (d ? { ...d, courseId: id } : d));
  }, []);
  const setFolderId = React.useCallback((id: string | null) => {
    setDialog(d => (d ? { ...d, folderId: id } : d));
  }, []);
  const retryRow = React.useCallback((id: string) => {
    queue.retry(id, dialog?.courseId ?? null);
  }, [queue, dialog]);

  // Once every file has settled: file the saved documents into the chosen
  // folder (the upload endpoint takes a course, not a folder), reload, and
  // take the student to where the new documents landed.
  React.useEffect(() => {
    if (!dialog?.started || !queue.finished || settled.current) return;
    settled.current = true;
    const { folderId, courseId } = dialog;
    const saved = queue.rows.filter(r => r.status === "done" && r.documentId);
    void (async () => {
      if (folderId && saved.length) {
        await Promise.all(saved.map(r =>
          data.moveDocuments([r.documentId!], { folder_id: folderId }, "")));
      }
      await data.reload();
      if (saved.some(r => r.category === "syllabus")) {
        setTimeout(() => { void data.reload(); }, SYLLABUS_REPOLL_MS);
        notifySyllabus();
      }
      if (saved.length) {
        goTo(folderId ? (`f:${folderId}` as Loc) : (`c:${courseId ?? "none"}` as Loc));
        select(saved[0].documentId!);
      }
    })();
  }, [dialog, queue.finished, queue.rows, data, goTo, select, notifySyllabus]);

  return { queue, dialog, closing, setCourseId, setFolderId, pickFiles, confirm, close, retryRow };
}
