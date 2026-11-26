/**
 * The words the Library puts on its scope: the heading, the name a search
 * narrows to, the empty state, and the course switcher's options.
 *
 * Pure, and apart from the component, because each one is a stack of
 * conditions the design spells out precisely and a test can pin.
 */
import type { EnrolledCourse } from "@/lib/api";
import type { Document as Doc } from "@/lib/types";

import { TYPES, courseLabel, parseLoc, type Loc } from "./libraryModel";

export interface ScopeInput {
  loc: Loc;
  /** The trimmed search text, as typed (not lowercased — it is quoted back). */
  query: string;
  type: Doc["category"] | "all";
  /** The course the scope sits in: the open course, or an open folder's. */
  course: EnrolledCourse | undefined;
  /** The open folder's name, when one is open. */
  folderName: string | undefined;
}

export interface ScopeLabels {
  /** The heading beside the course dot. */
  title: string;
  /** How a notice names this scope: "MATH210", "Midterm Prep". */
  name: string;
  emptyTitle: string;
  emptyBody: string;
}

export function scopeLabels({
  loc, query, type, course, folderName,
}: ScopeInput): ScopeLabels {
  const { kind, id } = parseLoc(loc);
  const isTrash = kind === "trash";
  const q = query.trim();
  const code = course ? courseLabel(course) : null;

  const title = isTrash
    ? "Trash"
    : kind === "all"
      ? "All Documents"
      : kind === "c"
        ? (id === "none" ? "No Course" : course ? `${code} · ${course.course_name}` : "Course")
        : `${code ? `${code} / ` : ""}${folderName ?? ""}`;

  const name = kind === "all" || isTrash
    ? ""
    : kind === "c"
      ? (id === "none" ? "No Course" : code ?? "this course")
      : folderName ?? "this folder";

  const emptyTitle = isTrash && !q
    ? "Trash Is Empty"
    : q
      ? `No Documents Match “${q}”`
      : type !== "all"
        ? `No ${TYPES[type].label} Here`
        : kind === "f" ? "This Folder Is Empty" : "Nothing Here Yet";

  const emptyBody = isTrash && !q
    ? "Documents you delete stay here for 30 days before they are removed."
    : q
      ? (kind === "all"
        ? "Try a shorter word, a course code, or a concept name."
        : `Nothing in ${name} matches. Try searching all documents, or search for a concept name.`)
      : kind === "f"
        ? "Drag documents here, or use Add to Folder in a document's menu."
        : "Upload a syllabus, lecture notes, or a reading and Sapling will summarize it.";

  return { title, name, emptyTitle, emptyBody };
}

export interface ScopeOptionInput {
  documents: Doc[];
  courses: EnrolledCourse[];
  loc: Loc;
  /** The course the current scope sits in, or null for "No Course". */
  scopeCourseId: string | null;
  /** How many documents are in the Trash, for its option's count. */
  trashCount: number;
  go: (loc: Loc) => void;
}

export interface ScopeOptionModel {
  id: string;
  sub: string;
  color: string | null;
  on: boolean;
  pick: () => void;
  /** The Trash option: a trash-can marker instead of a dot, under a divider. */
  trash?: boolean;
}

const plural = (n: number) => `${n} ${n === 1 ? "document" : "documents"}`;

/**
 * All Documents, then one per course, then No Course, then the Trash — each
 * with its count. The Trash used to be a button beside the switcher; owner's
 * call 2026-11-25 moved it in here, last, so the row holds one scope control.
 */
export function scopeOptions({
  documents, courses, loc, scopeCourseId, trashCount, go,
}: ScopeOptionInput): ScopeOptionModel[] {
  const { kind } = parseLoc(loc);
  const isTrash = kind === "trash";

  const all: ScopeOptionModel = {
    id: "All Documents",
    sub: `Every course · ${plural(documents.length)}`,
    color: "#597536",
    on: kind === "all",
    pick: () => go("all"),
  };

  const perCourse = courses.map(c => ({
    id: courseLabel(c),
    sub: `${c.course_name} · ${plural(documents.filter(d => d.course_id === c.course_id).length)}`,
    color: c.color,
    on: !isTrash && scopeCourseId === c.course_id,
    pick: () => go(`c:${c.course_id}` as Loc),
  }));

  const none: ScopeOptionModel = {
    id: "No Course",
    sub: `Unsorted · ${plural(documents.filter(d => !d.course_id).length)}`,
    color: null,
    on: !isTrash && kind !== "all" && scopeCourseId === null,
    pick: () => go("c:none"),
  };

  const trash: ScopeOptionModel = {
    id: "Trash",
    sub: `Deleted after 30 days · ${plural(trashCount)}`,
    color: null,
    on: isTrash,
    pick: () => go("trash"),
    trash: true,
  };

  return [all, ...perCourse, none, trash];
}
