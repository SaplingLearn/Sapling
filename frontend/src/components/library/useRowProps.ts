"use client";
/**
 * The per-row and per-folder props the list and the panel both take, plus the
 * drag-and-drop plumbing they share.
 *
 * One builder for both views, so a row and its card behave identically — the
 * design only changes how they look.
 */
import React from "react";

import type { EnrolledCourse } from "@/lib/api";
import type { DocFolder, Document as Doc } from "@/lib/types";

import { menuPositionFor } from "./DocMenu";
import type { DocRowProps, FolderRowProps } from "./LibraryList";
import { rowView } from "./rowModel";
import type { LibraryActions } from "./useLibraryActions";
import type { LibraryUi } from "./useLibraryUi";
import type { Loc } from "./libraryModel";

export type RowPropsFn = (doc: Doc, index: number)
  => Omit<DocRowProps, "columns" | "showCourse">;
export type FolderPropsFn = (folderId: string, index: number)
  => Omit<FolderRowProps, "columns" | "showCourse">;

export interface DropHandlers {
  onDragOver: (e: React.DragEvent) => void;
  onDragLeave: () => void;
  onDrop: (e: React.DragEvent) => void;
}

export interface RowPropsInput {
  ui: LibraryUi;
  act: LibraryActions;
  documents: Doc[];
  folders: DocFolder[];
  courseById: Map<string, EnrolledCourse>;
  checkedIds: string[];
  q: string;
  showCourse: boolean;
  isTrash: boolean;
  /** The scroll section the "⋯" dialog is positioned inside. */
  sectionRef: React.RefObject<HTMLDivElement | null>;
  openDoc: (docId: string) => void;
}

export interface RowPropsBundle {
  rowProps: RowPropsFn;
  folderProps: FolderPropsFn;
}

export function useRowProps(input: RowPropsInput): RowPropsBundle {
  const {
    ui, act, documents, folders, courseById, checkedIds, q, showCourse, isTrash,
    sectionRef, openDoc,
  } = input;

  const dropTarget = React.useCallback((
    key: string, onDrop: (ids: string[]) => void,
  ): DropHandlers => ({
    onDragOver: (e: React.DragEvent) => {
      e.preventDefault();
      if (ui.dropOn !== key) ui.setDropOn(key);
    },
    onDragLeave: () => ui.setDropOn(null),
    onDrop: (e: React.DragEvent) => {
      e.preventDefault();
      const ids = ui.dragIds.current;
      ui.dragIds.current = [];
      ui.setDropOn(null);
      if (ids.length) onDrop(ids);
    },
  }), [ui]);

  const editingDoc = ui.edit?.kind === "doc" ? ui.edit.id : null;
  const editingFolder = ui.edit?.kind === "folder" ? ui.edit.id : null;
  const draft = ui.edit ? ui.edit.draft : "";

  const rowProps: RowPropsFn = (doc, index) => {
    const checked = !!ui.checked[doc.id];
    return {
      view: rowView({
        doc, index, q, courses: courseById,
        leaving: ui.leaving.includes(doc.id), showCourse,
      }),
      doc,
      isTrash,
      // Checked rows are the selection; the single "current row" steps aside.
      selected: ui.selected === doc.id && checkedIds.length === 0,
      checked,
      dimmed: ui.dragging && ui.dragIds.current.includes(doc.id),
      menuOpen: ui.docMenu?.docId === doc.id,
      editing: editingDoc === doc.id,
      draft,
      onDraft: ui.setDraft,
      onCommit: act.commitEdit,
      onCancel: ui.cancelEdit,
      onSelect: () => {
        ui.setSelected(doc.id);
        ui.setSelectedFolder(null);
        ui.closeAllMenus();
      },
      onOpen: () => openDoc(doc.id),
      onCheck: (e: React.MouseEvent) => {
        e.stopPropagation();
        ui.setChecked(c => ({ ...c, [doc.id]: !c[doc.id] }));
        ui.setBulkConfirm(false);
      },
      onMenu: (e: React.MouseEvent) => {
        e.stopPropagation();
        if (ui.docMenu?.docId === doc.id) { ui.closeAllMenus(); return; }
        const section = sectionRef.current;
        if (!section) return;
        ui.setSelected(doc.id);
        ui.openDocMenu({
          docId: doc.id,
          position: menuPositionFor(e.currentTarget as HTMLElement, section),
          sub: null,
        });
      },
      onRestore: (e: React.MouseEvent) => {
        e.stopPropagation();
        act.restoreDocs([doc.id]);
      },
      onDragStart: (e: React.DragEvent) => {
        // Dragging a checked row drags every checked row with it.
        ui.dragIds.current = checked && checkedIds.length ? checkedIds : [doc.id];
        ui.setDragging(true);
        e.dataTransfer.effectAllowed = "move";
        try { e.dataTransfer.setData("text/plain", doc.id); } catch { /* older Safari */ }
      },
      onDragEnd: () => { ui.setDragging(false); ui.setDropOn(null); },
    };
  };

  const folderProps: FolderPropsFn = (folderId, index) => {
    const folder = folders.find(f => f.id === folderId)!;
    return {
      folder,
      count: documents.filter(d => d.folder_id === folder.id).length,
      selected: ui.selectedFolder === folder.id && checkedIds.length === 0,
      dragOver: ui.dropOn === `f:${folder.id}`,
      delay: `${index * 30 + 40}ms`,
      editing: editingFolder === folder.id,
      draft,
      onDraft: ui.setDraft,
      onCommit: act.commitEdit,
      onCancel: ui.cancelEdit,
      onSelect: () => {
        ui.setSelectedFolder(folder.id);
        ui.setSelected(null);
        ui.closeAllMenus();
      },
      onOpen: () => ui.setLoc(`f:${folder.id}` as Loc),
      ...dropTarget(`f:${folder.id}`, ids => act.moveToFolder(ids, folder.id)),
    };
  };

  return { rowProps, folderProps };
}
