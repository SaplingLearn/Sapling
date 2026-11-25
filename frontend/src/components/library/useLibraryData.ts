"use client";
/**
 * Everything the Library reads and writes, and the undo that goes with it.
 *
 * The prototype can undo by restoring a snapshot of its own arrays. Against a
 * real backend an undo has to be the INVERSE CALL, so each mutation here
 * returns the toast it should raise along with the closure that reverses it —
 * a delete undoes by restoring, a move undoes by moving back, a rename undoes
 * by renaming back.
 *
 * One mutation has no inverse and says so: Delete Forever raises a toast with
 * no Undo, because the row is gone. The prototype offers one; it is lying
 * about mock data, and this is the one place the two deliberately differ.
 */
import React from "react";

import { deleteDocument, getCourses, getDocuments, type EnrolledCourse } from "@/lib/api";
import {
  createFolder as apiCreateFolder,
  deleteFolder as apiDeleteFolder,
  getFolders,
  getTrashedDocuments,
  purgeDocument,
  renameFolder as apiRenameFolder,
  restoreDocument,
  updateDocument,
  type DocumentPatch,
} from "@/lib/libraryApi";
import type { DocFolder, Document as Doc } from "@/lib/types";
import { humanizeError } from "@/lib/errorMessage";
import { useLatestRequest } from "@/lib/useLatestRequest";

export interface Toast {
  msg: string;
  /** Absent when the action cannot be taken back. */
  undo?: () => Promise<void>;
}

export interface LibraryData {
  documents: Doc[];
  trash: Doc[];
  folders: DocFolder[];
  courses: EnrolledCourse[];
  loading: boolean;
  /** The documents load failed. Guides and folders fail quietly on their own. */
  loadError: boolean;
  reload: () => Promise<void>;
  retry: () => void;

  toast: Toast | null;
  flash: (toast: Toast) => void;
  clearToast: () => void;

  moveDocuments: (ids: string[], patch: DocumentPatch, where: string) => Promise<void>;
  renameDocument: (id: string, name: string) => Promise<void>;
  setCategory: (id: string, category: Doc["category"]) => Promise<void>;
  trashDocuments: (ids: string[]) => Promise<void>;
  restoreDocuments: (ids: string[]) => Promise<void>;
  purgeDocuments: (ids: string[]) => Promise<void>;
  addFolder: (name: string, courseId: string | null) => Promise<DocFolder | null>;
  renameFolderTo: (id: string, name: string) => Promise<void>;
  removeFolder: (id: string) => Promise<void>;
}

const TOAST_MS = 5000;

/** `“Determinants Lecture 7”`, or `3 documents` — how a toast names a target. */
function nameFor(ids: string[], docs: Doc[]): string {
  if (ids.length !== 1) return `${ids.length} documents`;
  const d = docs.find(x => x.id === ids[0]);
  return d ? `“${d.file_name.replace(/\.[^.]+$/, "")}”` : "that document";
}

export function useLibraryData(userId: string, userReady: boolean): LibraryData {
  const [documents, setDocuments] = React.useState<Doc[]>([]);
  const [trash, setTrash] = React.useState<Doc[]>([]);
  const [folders, setFolders] = React.useState<DocFolder[]>([]);
  const [courses, setCourses] = React.useState<EnrolledCourse[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [loadError, setLoadError] = React.useState(false);
  const [toast, setToast] = React.useState<Toast | null>(null);
  const toastTimer = React.useRef<ReturnType<typeof setTimeout> | null>(null);
  // Reloads overlap (an upload finishing while a move is in flight): the
  // latest one owns the list (#769, kept from the old Library).
  const loadReq = useLatestRequest();

  const clearToast = React.useCallback(() => {
    if (toastTimer.current) clearTimeout(toastTimer.current);
    setToast(null);
  }, []);

  const flash = React.useCallback((t: Toast) => {
    if (toastTimer.current) clearTimeout(toastTimer.current);
    setToast(t);
    toastTimer.current = setTimeout(() => setToast(null), TOAST_MS);
  }, []);

  React.useEffect(() => () => {
    if (toastTimer.current) clearTimeout(toastTimer.current);
  }, []);

  const reload = React.useCallback(async () => {
    if (!userId) return;
    const run = loadReq.begin();
    try {
      const [docs, crs] = await Promise.all([getDocuments(userId), getCourses(userId)]);
      if (!run.isCurrent()) return;
      setDocuments(docs.documents || []);
      setCourses(crs.courses || []);
      setLoadError(false);
    } catch (err) {
      if (!run.isCurrent()) return;
      console.error("library load failed", err);
      setLoadError(true);
    } finally {
      if (run.isCurrent()) setLoading(false);
    }
    // Folders and the Trash are secondary: the documents must never wait on
    // them, and an install whose migration has not run yet still works with an
    // empty folder list rather than an error page.
    try {
      const f = await getFolders(userId);
      if (run.isCurrent()) setFolders(f.folders || []);
    } catch (err) {
      console.error("library folders load failed", err);
    }
    try {
      const t = await getTrashedDocuments(userId);
      if (run.isCurrent()) setTrash(t.documents || []);
    } catch (err) {
      console.error("library trash load failed", err);
    }
  }, [userId, loadReq]);

  const retry = React.useCallback(() => {
    setLoading(true);
    void reload();
  }, [reload]);

  React.useEffect(() => {
    if (userReady && userId) void reload();
  }, [userReady, userId, reload]);

  /** Run a mutation, reload, and raise its toast. Reports a failure as a toast. */
  const run = React.useCallback(async (
    work: () => Promise<void>,
    msg: string,
    undo?: () => Promise<void>,
  ) => {
    try {
      await work();
      await reload();
      flash(undo ? { msg, undo } : { msg });
    } catch (err) {
      console.error("library action failed", err);
      flash({ msg: humanizeError(err, "That didn't work. Try again.") });
    }
  }, [reload, flash]);

  const moveDocuments = React.useCallback(async (
    ids: string[], patch: DocumentPatch, where: string,
  ) => {
    const before = documents.filter(d => ids.includes(d.id))
      .map(d => ({ id: d.id, course_id: d.course_id ?? null, folder_id: d.folder_id ?? null }));
    const label = nameFor(ids, documents);
    await run(
      async () => { await Promise.all(ids.map(id => updateDocument(id, userId, patch))); },
      where ? `Moved ${label} to ${where}` : `Removed ${label} from its folder`,
      async () => {
        await Promise.all(before.map(b =>
          updateDocument(b.id, userId, { course_id: b.course_id, folder_id: b.folder_id })));
        await reload();
        clearToast();
      },
    );
  }, [documents, userId, run, reload, clearToast]);

  const renameDocument = React.useCallback(async (id: string, name: string) => {
    const doc = documents.find(d => d.id === id);
    if (!doc || doc.file_name === name) return;
    const before = doc.file_name;
    await run(
      async () => { await updateDocument(id, userId, { file_name: name }); },
      `Renamed to “${name.replace(/\.[^.]+$/, "")}”`,
      async () => {
        await updateDocument(id, userId, { file_name: before });
        await reload();
        clearToast();
      },
    );
  }, [documents, userId, run, reload, clearToast]);

  const setCategory = React.useCallback(async (id: string, category: Doc["category"]) => {
    const before = documents.find(d => d.id === id)?.category;
    await run(
      async () => { await updateDocument(id, userId, { category }); },
      "Type updated",
      before ? async () => {
        await updateDocument(id, userId, { category: before });
        await reload();
        clearToast();
      } : undefined,
    );
  }, [documents, userId, run, reload, clearToast]);

  const trashDocuments = React.useCallback(async (ids: string[]) => {
    await run(
      async () => { await Promise.all(ids.map(id => deleteDocument(id, userId))); },
      ids.length === 1 ? "Moved to Trash" : `${ids.length} documents moved to Trash`,
      async () => {
        await Promise.all(ids.map(id => restoreDocument(id, userId)));
        await reload();
        clearToast();
      },
    );
  }, [userId, run, reload, clearToast]);

  const restoreDocuments = React.useCallback(async (ids: string[]) => {
    const label = ids.length === 1 ? nameFor(ids, trash) : `${ids.length} documents`;
    await run(
      async () => { await Promise.all(ids.map(id => restoreDocument(id, userId))); },
      ids.length === 1 ? `Restored ${label}` : `Restored ${label}`,
      async () => {
        await Promise.all(ids.map(id => deleteDocument(id, userId)));
        await reload();
        clearToast();
      },
    );
  }, [trash, userId, run, reload, clearToast]);

  const purgeDocuments = React.useCallback(async (ids: string[]) => {
    // No undo closure: the rows are gone. The Trash's own confirm step ("Click
    // Again to Delete Forever") is what stands in for one.
    await run(
      async () => { await Promise.all(ids.map(id => purgeDocument(id, userId))); },
      ids.length === 1 ? "Deleted forever" : `${ids.length} documents deleted forever`,
    );
  }, [userId, run]);

  const addFolder = React.useCallback(async (name: string, courseId: string | null) => {
    try {
      const folder = await apiCreateFolder(userId, name, courseId);
      setFolders(prev => [...prev, folder]);
      return folder;
    } catch (err) {
      console.error("create folder failed", err);
      flash({ msg: humanizeError(err, "Couldn't make that folder. Try again.") });
      return null;
    }
  }, [userId, flash]);

  const renameFolderTo = React.useCallback(async (id: string, name: string) => {
    const before = folders.find(f => f.id === id);
    if (!before || before.name === name) return;
    setFolders(prev => prev.map(f => (f.id === id ? { ...f, name } : f)));
    try {
      await apiRenameFolder(id, userId, name);
    } catch (err) {
      console.error("rename folder failed", err);
      setFolders(prev => prev.map(f => (f.id === id ? before : f)));
      flash({ msg: humanizeError(err, "Couldn't rename that folder. Try again.") });
    }
  }, [folders, userId, flash]);

  const removeFolder = React.useCallback(async (id: string) => {
    const folder = folders.find(f => f.id === id);
    if (!folder) return;
    const inside = documents.filter(d => d.folder_id === id).map(d => d.id);
    await run(
      async () => { await apiDeleteFolder(id, userId); },
      `Deleted folder “${folder.name}”. Its documents are still in the course.`,
      // Undo re-creates the folder and re-files what was in it. The folder's
      // id is new — nothing outside the Library holds one, and the student
      // sees their folder back, which is what Undo promises.
      async () => {
        const fresh = await apiCreateFolder(userId, folder.name, folder.course_id);
        await Promise.all(inside.map(docId =>
          updateDocument(docId, userId, { folder_id: fresh.id })));
        await reload();
        clearToast();
      },
    );
  }, [folders, documents, userId, run, reload, clearToast]);

  return {
    documents, trash, folders, courses, loading, loadError,
    reload, retry,
    toast, flash, clearToast,
    moveDocuments, renameDocument, setCategory,
    trashDocuments, restoreDocuments, purgeDocuments,
    addFolder, renameFolderTo, removeFolder,
  };
}
