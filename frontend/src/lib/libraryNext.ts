/**
 * Library → Tree / Quiz deep links after upload (W8.1 / W8.1b).
 *
 * Status copy from `documents.check_items_status` (A128); hrefs reuse the
 * existing Tree and Quiz routes — no second planner.
 */

import { buildQuizHref } from "@/lib/quiz/source";
import type { CheckItemsStatus, ConceptNote } from "@/lib/types";

export type { CheckItemsStatus };

export const LIBRARY_RETURN = "/library";

/** Match graph_service._normalize_concept (case + whitespace fold). */
export function normalizeConceptName(name: string): string {
  return name.trim().replace(/\s+/g, " ").toLowerCase();
}

/**
 * Graph node ids already stamped on document concept notes (list wire, W8.1c).
 * Order follows the notes; blanks skipped.
 */
export function conceptIdsFromNotes(
  notes: readonly ConceptNote[] | null | undefined,
): string[] {
  if (!notes?.length) return [];
  const out: string[] = [];
  for (const note of notes) {
    const id = note.node_id?.trim();
    if (id) out.push(id);
  }
  return out;
}

type GraphNameNode = {
  id?: string | null;
  concept_name?: string | null;
  course_id?: string | null;
};

/**
 * Map concept names → graph node ids for a course (upload success path).
 * Same normalize as the documents list attach.
 */
export function conceptIdsFromNames(
  names: readonly string[] | null | undefined,
  nodes: readonly GraphNameNode[],
  courseId?: string | null,
): string[] {
  if (!names?.length || !courseId?.trim()) return [];
  const course = courseId.trim();
  const byName = new Map<string, string>();
  for (const node of nodes) {
    const id = node.id?.trim();
    const name = node.concept_name;
    if (!id || !name || (node.course_id ?? "").trim() !== course) continue;
    const key = normalizeConceptName(name);
    if (key && !byName.has(key)) byName.set(key, id);
  }
  const out: string[] = [];
  for (const name of names) {
    const id = byName.get(normalizeConceptName(name));
    if (id) out.push(id);
  }
  return out;
}

/** Course map. With a course id, open Tree filtered to that course (`?course=`). */
export function libraryTreeHref(courseId?: string | null): string {
  const id = courseId?.trim();
  return id ? `/tree?course=${encodeURIComponent(id)}` : "/tree";
}

/**
 * Quiz that returns to Library; `start=1` begins on arrival.
 * Prefer a concept node id when the document has one; else course-scoped.
 */
export function libraryQuizHref(
  courseId: string,
  conceptIds?: readonly string[] | null,
): string {
  const concept = conceptIds?.map((id) => id.trim()).find(Boolean);
  return buildQuizHref(
    concept ? { concept } : { course: courseId },
    { kind: "link", returnTo: LIBRARY_RETURN },
    { start: true },
  );
}

export interface LibraryNextInput {
  courseId?: string | null;
  /**
   * Graph node ids for concepts on this document, when known. Prefer the first
   * for a concept-scoped quiz; omit / empty keeps the course-scoped fallback.
   */
  conceptIds?: readonly string[] | null;
  /** Concepts extracted for this document (names or count). */
  conceptCount: number;
  /** From the documents list; null/undefined = never drafted or unknown. */
  checkItemsStatus?: CheckItemsStatus | null;
  /** Student's `learning_loop` flag is on. */
  loopOn: boolean;
  /** `hide_tree` is on for this student. */
  treeHidden: boolean;
  /** `hide_quiz` is on for this student. */
  quizHidden: boolean;
  /**
   * Upload just finished and drafting has not been read back yet. With the
   * loop on, treat as checks still drafting (post-roll runs after the SSE
   * `done`).
   */
  justUploaded?: boolean;
}

export interface LibraryNext {
  /** One short status line, or null when there is nothing to say. */
  statusLine: string | null;
  treeHref: string | null;
  /** Present when Quiz is allowed and checks (or concepts) are ready to practice. */
  quizHref: string | null;
}

function statusLineFor(input: LibraryNextInput): string | null {
  const parts: string[] = [];
  if (input.conceptCount > 0) {
    parts.push(
      input.conceptCount === 1 ? "1 concept added" : `${input.conceptCount} concepts added`,
    );
  }
  if (input.loopOn) {
    const status = input.checkItemsStatus;
    if (status === "pending" || (input.justUploaded && status == null)) {
      parts.push("Checks drafting");
    } else if (status === "done") {
      parts.push("Checks ready");
    }
  }
  return parts.length ? parts.join(" · ") : null;
}

/** Whether the Quiz CTA should open for this document. */
export function quizReady(input: Pick<LibraryNextInput, "loopOn" | "checkItemsStatus" | "conceptCount" | "courseId" | "quizHidden">): boolean {
  if (input.quizHidden || !input.courseId) return false;
  if (input.loopOn) return input.checkItemsStatus === "done";
  // Loop off: course quiz is still a real destination once concepts exist.
  return input.conceptCount > 0;
}

/**
 * Status copy + Tree / Quiz hrefs for a Library document (or a just-finished
 * upload row). Callers hide a null href.
 */
export function libraryNext(input: LibraryNextInput): LibraryNext {
  const showSpine = input.conceptCount > 0 || Boolean(input.courseId) || input.justUploaded;
  return {
    statusLine: statusLineFor(input),
    treeHref: showSpine && !input.treeHidden ? libraryTreeHref(input.courseId) : null,
    quizHref: quizReady(input)
      ? libraryQuizHref(input.courseId!, input.conceptIds)
      : null,
  };
}
