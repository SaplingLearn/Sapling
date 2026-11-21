"use client";
/**
 * What the open scope resolves to: which documents and folders it shows, the
 * course it sits in, and the grid the rows are laid out on.
 *
 * Everything here is derived — no state of its own — but it is the derivation
 * the whole page depends on, so it is named and memoised in one place rather
 * than spread through the component.
 */
import React from "react";

import type { EnrolledCourse } from "@/lib/api";
import type { DocFolder, Document as Doc } from "@/lib/types";

import { filterDocuments, foldersAtLoc, parseLoc } from "./libraryModel";
import { listColumns } from "./rowModel";
import type { LibraryUi } from "./useLibraryUi";

export interface LibraryScope {
  kind: "all" | "trash" | "c" | "f";
  /** The course or folder id in the location, when it has one. */
  locId: string | null;
  isTrash: boolean;
  /** The search text, trimmed and lowercased — what the filters match on. */
  q: string;
  /** Live documents, or the Trash's. */
  source: Doc[];
  /** Location + search, BEFORE the type filter: the Type menu's counts. */
  scoped: Doc[];
  /** What the list actually renders, type-filtered and sorted. */
  rows: Doc[];
  folderItems: DocFolder[];
  typeCounts: Record<string, number>;
  checkedIds: string[];
  /** The Course column only earns its width when more than one can show. */
  showCourse: boolean;
  columns: string;
  openFolder: DocFolder | undefined;
  scopeCourseId: string | null;
  scopeCourse: EnrolledCourse | undefined;
  /** A search is running, and it is narrowed to a course or folder. */
  searchScoped: boolean;
  allChecked: boolean;
}

export function useLibraryScope(
  ui: LibraryUi,
  documents: Doc[],
  trash: Doc[],
  folders: DocFolder[],
  courses: EnrolledCourse[],
  courseById: Map<string, EnrolledCourse>,
): LibraryScope {
  const { kind, id: locId } = parseLoc(ui.loc);
  const isTrash = kind === "trash";
  const q = ui.query.trim().toLowerCase();
  const source = isTrash ? trash : documents;

  const { scoped, list: rows } = React.useMemo(() => filterDocuments({
    docs: source, loc: ui.loc, q, type: ui.type, sort: ui.sortKey, folders, courses,
  }), [source, ui.loc, q, ui.type, ui.sortKey, folders, courses]);

  const folderItems = React.useMemo(
    () => foldersAtLoc(folders, ui.loc, q), [folders, ui.loc, q],
  );

  const typeCounts = React.useMemo(() => {
    const counts: Record<string, number> = {};
    for (const d of scoped) counts[d.category] = (counts[d.category] || 0) + 1;
    return counts;
  }, [scoped]);

  // A checkbox survives a scope change only while its document is still in
  // view, so the bulk bar can never act on something that is not listed.
  const checkedIds = React.useMemo(
    () => Object.keys(ui.checked).filter(k => ui.checked[k] && source.some(d => d.id === k)),
    [ui.checked, source],
  );

  const openFolder = kind === "f" ? folders.find(f => f.id === locId) : undefined;
  const folderCourseId = openFolder ? openFolder.course_id : null;
  const courseScopeId = locId === "none" ? null : locId;
  const scopeCourseId = kind === "c" ? courseScopeId : folderCourseId;
  const scopeCourse = scopeCourseId ? courseById.get(scopeCourseId) : undefined;

  const showCourse = kind === "all" || isTrash;
  const allChecked = rows.length > 0 && rows.every(d => ui.checked[d.id]);

  return {
    kind, locId, isTrash, q, source, scoped, rows, folderItems, typeCounts, checkedIds,
    showCourse, columns: listColumns({ isTrash, showCourse }),
    openFolder, scopeCourseId, scopeCourse,
    searchScoped: q.length > 0 && kind !== "all",
    allChecked,
  };
}
