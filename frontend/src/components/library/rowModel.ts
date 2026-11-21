/**
 * What one row shows, derived from a document plus the state around it.
 *
 * The design computes this inside `renderVals()`; it lives here so the list
 * row and the panel card read the same values, and so the two pieces that are
 * easy to get subtly wrong — which subtitle a search match produces, and the
 * stagger delay — are in one testable place.
 */
import type { EnrolledCourse } from "@/lib/api";
import type { Document as Doc } from "@/lib/types";

import {
  FMT, FMT_FALLBACK, TYPES, addedLabel, courseLabel, fmtOf, highlight, titleOf,
} from "./libraryModel";

export interface RowView {
  id: string;
  /** The title, split around the search match so the middle can be marked. */
  name: { a: string; m: string; b: string };
  /** The line under the title: the summary, or what the search matched on. */
  sub: string;
  /** Green when the subtitle is a search hit rather than the plain summary. */
  subColor: string;
  fmt: string;
  fmtColor: string;
  typeLabel: string;
  typeColor: string;
  courseLabel: string;
  courseColor: string | null;
  /** "" when the count is unknown; the design's em dash is rendered instead. */
  pages: string;
  added: string;
  /** Panel cards put course, type and pages on one line. */
  cardMeta: string;
  /** The row's entrance (or exit) animation, ready for `animation:`. */
  anim: string;
  /** Stagger: rows arrive 30 ms apart, the first twelve only. */
  delay: string;
}

export interface RowViewInput {
  doc: Doc;
  index: number;
  /** The trimmed, lowercased search text. */
  q: string;
  courses: Map<string, EnrolledCourse>;
  /** True while the row is animating out (a delete or a move). */
  leaving: boolean;
  /** The course column is hidden inside a single course. */
  showCourse: boolean;
}

export function rowView({
  doc, index, q, courses, leaving, showCourse,
}: RowViewInput): RowView {
  const title = titleOf(doc);
  const summary = doc.summary || "";
  const course = doc.course_id ? courses.get(doc.course_id) : undefined;

  const titleHit = !!q && title.toLowerCase().includes(q);
  const conceptHit = !titleHit && q
    ? (doc.concept_notes || []).find(c => c.name.toLowerCase().includes(q))?.name
    : undefined;
  const summaryHit = !titleHit && !conceptHit && !!q && summary.toLowerCase().includes(q);

  const sub = conceptHit
    ? `Linked concept: ${conceptHit}`
    : summaryHit ? `In summary: ${summary}` : summary;

  const fmt = fmtOf(doc);
  const pages = doc.page_count == null ? "" : String(doc.page_count);
  const type = TYPES[doc.category];
  const courseName = course ? courseLabel(course) : "No Course";

  return {
    id: doc.id,
    name: highlight(title, q),
    sub,
    subColor: conceptHit || summaryHit ? "#445D22" : "#6F6857",
    fmt,
    fmtColor: FMT[fmt] || FMT_FALLBACK,
    typeLabel: type.label,
    typeColor: type.color,
    courseLabel: courseName,
    courseColor: course?.color || null,
    pages,
    added: addedLabel(doc.created_at),
    cardMeta: (showCourse ? `${courseName} · ` : "")
      + `${type.label}${pages ? ` · ${pages} ${pages === "1" ? "page" : "pages"}` : ""}`,
    anim: leaving
      ? "sapRowOut 230ms cubic-bezier(0.4, 0, 1, 1) both"
      : "sapSlideUp 420ms cubic-bezier(0.2, 0.7, 0.2, 1) both",
    delay: `${Math.min(index, 12) * 30 + 40}ms`,
  };
}

/**
 * The miniature first page a panel card shows.
 *
 * The prototype ships a hand-written `page` per mock document (a heading, two
 * lines, a formula). A real library has the document's own title, its summary
 * and the concepts the pipeline pulled out, so the card is built from those:
 * the heading is the title, the two lines are the first two sentences of the
 * summary, and the mono line names the first concept — which is what the
 * prototype's formula line is doing, standing for "the thing this page is
 * about". A document still being processed has none of it and shows the
 * ruled-paper placeholder alone, exactly as a blank one does.
 */
export interface PagePreview {
  heading: string;
  lines: string[];
  accent: string;
}

export function pagePreview(doc: Doc): PagePreview {
  const summary = (doc.summary || "").trim();
  const lines = summary
    ? summary.split(/(?<=[.!?])\s+/).slice(0, 2).map(s => s.trim()).filter(Boolean)
    : [];
  const first = (doc.concept_notes || [])[0]?.name || "";
  return { heading: titleOf(doc), lines, accent: first };
}

/** The grid track list the header and every row share, per scope. */
export function listColumns(opts: { isTrash: boolean; showCourse: boolean }): string {
  if (opts.isTrash) return "24px minmax(0, 1fr) 120px 120px 56px 64px 96px";
  if (opts.showCourse) return "24px minmax(0, 1fr) 120px 120px 56px 64px 40px";
  return "24px minmax(0, 1fr) 140px 64px 72px 40px";
}
