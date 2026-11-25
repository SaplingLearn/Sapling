"use client";
/**
 * The Library's verbs: move, trash, restore, purge, rename, re-type, scan, and
 * the two "New …" creators.
 *
 * Each one is the small amount of glue between a control and `useLibraryData`:
 * it plays the row's exit animation where the design has one, clears the
 * selection or the checkboxes the action invalidates, and closes whatever menu
 * it was invoked from.
 */
import React from "react";

import { scanCourseConcepts, scanDocumentConcepts, type EnrolledCourse } from "@/lib/api";
import { humanizeError } from "@/lib/errorMessage";
import type { DocFolder } from "@/lib/types";

import { courseLabel, titleOf, uniqueName, type Loc } from "./libraryModel";
import type { LibraryData } from "./useLibraryData";
import type { LibraryUi } from "./useLibraryUi";

export type ScanState = "idle" | "scanning" | "done";

interface Toasts {
  success: (msg: string) => void;
  info: (msg: string) => void;
  error: (msg: string) => void;
}

export interface LibraryActionsInput {
  data: LibraryData;
  ui: LibraryUi;
  userId: string;
  toast: Toasts;
  courseById: Map<string, EnrolledCourse>;
  folders: DocFolder[];
  /** The course the open scope sits in; a new item inherits it. */
  scopeCourseId: string | null;
  openFolder: DocFolder | undefined;
}

export interface LibraryActions {
  moveToFolder: (ids: string[], folderId: string | null) => void;
  moveToCourse: (ids: string[], courseId: string | null) => void;
  trashDocs: (ids: string[]) => void;
  restoreDocs: (ids: string[]) => void;
  purgeDocs: (ids: string[]) => void;
  commitEdit: () => void;
  newDocument: () => void;
  newFolder: () => void;
  deleteOpenFolder: () => void;

  scans: Record<string, ScanState>;
  runScan: (docId: string) => void;
  courseScanning: boolean;
  runCourseScan: (courseId: string) => void;
}

/** The plural the scan toasts use: "1 concept" / "3 concepts". */
const concepts = (n: number) => `${n} concept${n === 1 ? "" : "s"}`;

export function useLibraryActions(input: LibraryActionsInput): LibraryActions {
  const { data, ui, userId, toast, courseById, folders, scopeCourseId, openFolder } = input;
  const [scans, setScans] = React.useState<Record<string, ScanState>>({});
  const [courseScanning, setCourseScanning] = React.useState(false);

  const moveToFolder = React.useCallback((ids: string[], folderId: string | null) => {
    const folder = folderId ? folders.find(f => f.id === folderId) : undefined;
    // A folder lives inside one course, so filing into it also moves the
    // document to that course — the one place a move changes two fields.
    void data.moveDocuments(
      ids,
      folder ? { folder_id: folder.id, course_id: folder.course_id } : { folder_id: null },
      folder?.name ?? "",
    );
  }, [data, folders]);

  const moveToCourse = React.useCallback((ids: string[], courseId: string | null) => {
    const c = courseId ? courseById.get(courseId) : undefined;
    void data.moveDocuments(ids, { course_id: courseId }, c ? courseLabel(c) : "No Course");
  }, [data, courseById]);

  const trashDocs = React.useCallback((ids: string[]) => {
    ui.closeAllMenus();
    ui.leave(ids, async () => {
      await data.trashDocuments(ids);
      ui.clearChecked();
      ui.setSelected(prev => (prev && ids.includes(prev) ? null : prev));
    });
  }, [data, ui]);

  const restoreDocs = React.useCallback((ids: string[]) => {
    ui.leave(ids, async () => {
      await data.restoreDocuments(ids);
      ui.clearChecked();
    });
  }, [data, ui]);

  const purgeDocs = React.useCallback((ids: string[]) => {
    ui.leave(ids, async () => {
      await data.purgeDocuments(ids);
      ui.clearChecked();
      ui.setEmptyConfirm(false);
      ui.setBulkConfirm(false);
    });
  }, [data, ui]);

  const commitEdit = React.useCallback(() => {
    const edit = ui.edit;
    ui.cancelEdit();
    if (!edit) return;
    if (edit.kind === "folder") {
      const taken = data.folders.filter(f => f.id !== edit.id).map(f => f.name);
      void data.renameFolderTo(edit.id, uniqueName(edit.draft.trim() || "New Folder", taken));
      return;
    }
    const doc = data.documents.find(d => d.id === edit.id);
    if (!doc) return;
    const taken = data.documents.filter(d => d.id !== edit.id).map(titleOf);
    const base = edit.draft.trim() || uniqueName("New Document", taken);
    // The row shows the name without its extension, but the column stores the
    // file name — so the extension is put back unless the student typed one.
    const ext = doc.file_name.match(/\.[^.]+$/)?.[0] ?? "";
    void data.renameDocument(edit.id, base.endsWith(ext) ? base : base + ext);
  }, [data, ui]);

  const newDocument = React.useCallback(() => {
    ui.closeAllMenus();
    void (async () => {
      const name = uniqueName("New Document", data.documents.map(titleOf));
      const doc = await data.createDocument(name, scopeCourseId, openFolder?.id ?? null);
      if (!doc) return;
      ui.setSelected(doc.id);
      ui.startEdit(doc.id, "doc", name);
    })();
  }, [data, ui, scopeCourseId, openFolder]);

  const newFolder = React.useCallback(() => {
    ui.closeAllMenus();
    void (async () => {
      const name = uniqueName("New Folder", data.folders.map(f => f.name));
      const folder = await data.addFolder(name, scopeCourseId);
      if (!folder) return;
      // The new folder shows at its course's root, which may not be the open
      // scope — go there so the student can see what they just made.
      ui.setLoc(`c:${scopeCourseId ?? "none"}` as Loc);
      ui.startEdit(folder.id, "folder", name);
    })();
  }, [data, ui, scopeCourseId]);

  const deleteOpenFolder = React.useCallback(() => {
    if (!openFolder) return;
    ui.setLoc(`c:${openFolder.course_id ?? "none"}` as Loc);
    void data.removeFolder(openFolder.id);
  }, [data, ui, openFolder]);

  const runScan = React.useCallback((docId: string) => {
    setScans(s => ({ ...s, [docId]: "scanning" }));
    void (async () => {
      try {
        const res = await scanDocumentConcepts(docId, userId);
        setScans(s => ({ ...s, [docId]: "done" }));
        if (res.added > 0) toast.success(`Added ${concepts(res.added)} to your graph.`);
        else if (res.existing > 0) {
          toast.info(`Course graph already covers this (${concepts(res.existing)}).`);
        } else toast.info("Nothing to add from this document yet.");
      } catch (err) {
        setScans(s => ({ ...s, [docId]: "idle" }));
        toast.error(humanizeError(err, "Couldn't scan that document. Try again."));
      }
    })();
  }, [userId, toast]);

  const runCourseScan = React.useCallback((courseId: string) => {
    setCourseScanning(true);
    const course = courseById.get(courseId);
    const label = course ? courseLabel(course) : "Course";
    void (async () => {
      try {
        const res = await scanCourseConcepts(courseId, userId);
        if (res.added > 0) toast.success(`${label}: added ${concepts(res.added)}.`);
        else if (res.existing > 0) {
          toast.info(`${label}: graph already covers it (${concepts(res.existing)}).`);
        } else toast.info(`${label}: nothing to add yet.`);
      } catch (err) {
        toast.error(humanizeError(err, "Couldn't scan that course. Try again."));
      } finally {
        setCourseScanning(false);
      }
    })();
  }, [userId, toast, courseById]);

  return {
    moveToFolder, moveToCourse, trashDocs, restoreDocs, purgeDocs,
    commitEdit, newDocument, newFolder, deleteOpenFolder,
    scans, runScan, courseScanning, runCourseScan,
  };
}
