"use client";
/**
 * The Library's interaction state: which scope is open, what is selected or
 * checked, which menu is showing, what is being dragged, and the in-place
 * rename.
 *
 * Kept apart from `Library.tsx` so the component is layout and wiring, and so
 * the two timing-sensitive behaviours — a menu that plays its exit animation
 * before it unmounts, and a row that plays its exit before it leaves the list
 * — live in one place with their delays named.
 */
import React from "react";

import type { Document as Doc } from "@/lib/types";
import type { Loc, SortKey } from "./libraryModel";
import type { DocMenuSub, MenuPosition } from "./DocMenu";

/** The prototype's menu-exit duration; `sapMenuOut` runs for exactly this. */
const MENU_EXIT_MS = 130;
/** `sapRowOut` runs for 230 ms, so the row is gone the moment it finishes. */
const ROW_EXIT_MS = 230;

export interface OpenDocMenu {
  docId: string;
  position: MenuPosition;
  sub: DocMenuSub;
}

export type EditTarget = { id: string; kind: "doc" | "folder"; draft: string } | null;

export interface LibraryUi {
  loc: Loc;
  setLoc: (loc: Loc) => void;
  query: string;
  setQuery: (q: string) => void;
  type: Doc["category"] | "all";
  setType: (t: Doc["category"] | "all") => void;
  sortKey: SortKey;
  setSortKey: (s: SortKey) => void;
  view: "list" | "panel";
  setView: (v: "list" | "panel") => void;

  selected: string | null;
  /** A setter, not a value: the arrow keys move from whatever is selected now. */
  setSelected: React.Dispatch<React.SetStateAction<string | null>>;
  selectedFolder: string | null;
  setSelectedFolder: (id: string | null) => void;
  checked: Record<string, boolean>;
  setChecked: React.Dispatch<React.SetStateAction<Record<string, boolean>>>;
  clearChecked: () => void;

  /** Which popover is open, and whether it is on its way out. */
  closing: boolean;
  headerMenu: "upload" | "sort" | "type" | null;
  openHeaderMenu: (m: "upload" | "sort" | "type" | null) => void;
  courseMenu: boolean;
  openCourseMenu: (open: boolean) => void;
  bulkMenu: boolean;
  openBulkMenu: (open: boolean) => void;
  docMenu: OpenDocMenu | null;
  openDocMenu: (m: OpenDocMenu | null) => void;
  setDocMenuSub: (sub: DocMenuSub) => void;
  closeAllMenus: () => void;

  edit: EditTarget;
  startEdit: (id: string, kind: "doc" | "folder", draft: string) => void;
  setDraft: (draft: string) => void;
  cancelEdit: () => void;

  /** The drop target under the pointer, e.g. `f:…` for a folder. */
  dropOn: string | null;
  setDropOn: (key: string | null) => void;
  dragIds: React.RefObject<string[]>;
  dragging: boolean;
  setDragging: (v: boolean) => void;

  /** Ids currently playing `sapRowOut`. */
  leaving: string[];
  /** Plays the exit on `ids`, then runs `after`. */
  leave: (ids: string[], after: () => void | Promise<void>) => void;

  emptyConfirm: boolean;
  setEmptyConfirm: (v: boolean) => void;
  bulkConfirm: boolean;
  setBulkConfirm: (v: boolean) => void;
}

export function useLibraryUi(): LibraryUi {
  const [loc, setLocState] = React.useState<Loc>("all");
  const [query, setQuery] = React.useState("");
  const [type, setType] = React.useState<Doc["category"] | "all">("all");
  const [sortKey, setSortKey] = React.useState<SortKey>("recent");
  const [view, setView] = React.useState<"list" | "panel">("list");

  const [selected, setSelected] = React.useState<string | null>(null);
  const [selectedFolder, setSelectedFolder] = React.useState<string | null>(null);
  const [checked, setChecked] = React.useState<Record<string, boolean>>({});

  const [headerMenu, setHeaderMenu] = React.useState<"upload" | "sort" | "type" | null>(null);
  const [courseMenu, setCourseMenu] = React.useState(false);
  const [bulkMenu, setBulkMenu] = React.useState(false);
  const [docMenu, setDocMenu] = React.useState<OpenDocMenu | null>(null);
  const [closing, setClosing] = React.useState(false);

  const [edit, setEdit] = React.useState<EditTarget>(null);
  const [dropOn, setDropOn] = React.useState<string | null>(null);
  const dragIds = React.useRef<string[]>([]);
  const [dragging, setDragging] = React.useState(false);

  const [leaving, setLeaving] = React.useState<string[]>([]);
  const [emptyConfirm, setEmptyConfirm] = React.useState(false);
  const [bulkConfirm, setBulkConfirm] = React.useState(false);

  const exitTimer = React.useRef<ReturnType<typeof setTimeout> | null>(null);
  const leaveTimer = React.useRef<ReturnType<typeof setTimeout> | null>(null);

  React.useEffect(() => () => {
    if (exitTimer.current) clearTimeout(exitTimer.current);
    if (leaveTimer.current) clearTimeout(leaveTimer.current);
  }, []);

  /**
   * Close every popover through `sapMenuOut`. Opening one while another is on
   * its way out cancels the exit, so a fast click does not leave a ghost.
   */
  const closeAllMenus = React.useCallback(() => {
    setClosing(true);
    if (exitTimer.current) clearTimeout(exitTimer.current);
    exitTimer.current = setTimeout(() => {
      setClosing(false);
      setHeaderMenu(null);
      setCourseMenu(false);
      setBulkMenu(false);
      setDocMenu(null);
    }, MENU_EXIT_MS);
  }, []);

  const cancelExit = React.useCallback(() => {
    if (exitTimer.current) clearTimeout(exitTimer.current);
    setClosing(false);
  }, []);

  const openHeaderMenu = React.useCallback((m: "upload" | "sort" | "type" | null) => {
    if (m === null) return closeAllMenus();
    cancelExit();
    setCourseMenu(false);
    setBulkMenu(false);
    setDocMenu(null);
    setHeaderMenu(m);
  }, [closeAllMenus, cancelExit]);

  const openCourseMenu = React.useCallback((open: boolean) => {
    if (!open) return closeAllMenus();
    cancelExit();
    setHeaderMenu(null);
    setBulkMenu(false);
    setDocMenu(null);
    setCourseMenu(true);
  }, [closeAllMenus, cancelExit]);

  const openBulkMenu = React.useCallback((open: boolean) => {
    if (!open) return closeAllMenus();
    cancelExit();
    setHeaderMenu(null);
    setCourseMenu(false);
    setDocMenu(null);
    setBulkMenu(true);
  }, [closeAllMenus, cancelExit]);

  const openDocMenu = React.useCallback((m: OpenDocMenu | null) => {
    if (m === null) return closeAllMenus();
    cancelExit();
    setHeaderMenu(null);
    setCourseMenu(false);
    setBulkMenu(false);
    setDocMenu(m);
  }, [closeAllMenus, cancelExit]);

  const setDocMenuSub = React.useCallback((sub: DocMenuSub) => {
    setDocMenu(m => (m ? { ...m, sub } : m));
  }, []);

  const setLoc = React.useCallback((next: Loc) => {
    setLocState(next);
    setChecked({});
    setSelectedFolder(null);
    setBulkConfirm(false);
    setEmptyConfirm(false);
    closeAllMenus();
  }, [closeAllMenus]);

  const clearChecked = React.useCallback(() => {
    setChecked({});
    setBulkConfirm(false);
  }, []);

  const startEdit = React.useCallback((id: string, kind: "doc" | "folder", draft: string) => {
    setEdit({ id, kind, draft });
  }, []);
  const setDraft = React.useCallback((draft: string) => {
    setEdit(e => (e ? { ...e, draft } : e));
  }, []);
  const cancelEdit = React.useCallback(() => setEdit(null), []);

  const leave = React.useCallback((ids: string[], after: () => void | Promise<void>) => {
    if (!ids.length) { void after(); return; }
    setLeaving(ids);
    if (leaveTimer.current) clearTimeout(leaveTimer.current);
    leaveTimer.current = setTimeout(() => {
      setLeaving([]);
      void after();
    }, ROW_EXIT_MS);
  }, []);

  return {
    loc, setLoc, query, setQuery, type, setType, sortKey, setSortKey, view, setView,
    selected, setSelected, selectedFolder, setSelectedFolder,
    checked, setChecked, clearChecked,
    closing, headerMenu, openHeaderMenu, courseMenu, openCourseMenu,
    bulkMenu, openBulkMenu, docMenu, openDocMenu, setDocMenuSub, closeAllMenus,
    edit, startEdit, setDraft, cancelEdit,
    dropOn, setDropOn, dragIds, dragging, setDragging,
    leaving, leave,
    emptyConfirm, setEmptyConfirm, bulkConfirm, setBulkConfirm,
  };
}
