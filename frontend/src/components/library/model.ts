// Pure helpers behind the Library screen (design: "Sapling Library.dc.html").
import type { Document as Doc } from "@/lib/types";
import type { EnrolledCourse } from "@/lib/api";

export type Category = Doc["category"];

export const TYPES: Record<Category, { label: string; color: string }> = {
  lecture_notes: { label: "Lecture Notes", color: "#6E8B4E" },
  slides: { label: "Slides", color: "#B8873F" },
  reading: { label: "Reading", color: "#7A4A78" },
  study_guide: { label: "Study Guide", color: "#3E7F7A" },
  assignment: { label: "Assignment", color: "#B4562C" },
  syllabus: { label: "Syllabus", color: "#3F3B31" },
  other: { label: "Other", color: "#8A8372" },
};

export const typeOf = (c: string) => TYPES[c as Category] ?? TYPES.other;

/** Chip order from the design; "other" has no chip (it still shows under All Types). */
export const TYPE_CHIPS: (Category | "all")[] = [
  "all", "lecture_notes", "slides", "reading", "study_guide", "assignment", "syllabus",
];

export const FMT_COLORS: Record<string, string> = {
  PDF: "#B4562C", PPTX: "#B8873F", DOCX: "#3E6E9E", NOTE: "#3E6E9E",
};

/** Course dot colors when an enrollment has none of its own. */
const COURSE_PALETTE = ["#C06020", "#2868B0", "#3E8030", "#7030A8", "#3E7F7A", "#B8873F", "#A8443F"];

export type SortKey = "recent" | "oldest" | "name" | "course" | "type";
// "Most Pages" from the design is left out: documents carry no page count.
export const SORTS: [SortKey, string][] = [
  ["recent", "Recently Added"], ["oldest", "Oldest First"], ["name", "Name A–Z"],
  ["course", "Course"], ["type", "Type"],
];

export interface CourseInfo {
  id: string;
  code: string;
  name: string;
  color: string;
}

/** One entry per abstract course (#449: the API can return one row per enrollment). */
export function dedupeCourses(courses: EnrolledCourse[]): CourseInfo[] {
  const seen = new Map<string, CourseInfo>();
  for (const c of courses) {
    if (seen.has(c.course_id)) continue;
    seen.set(c.course_id, {
      id: c.course_id,
      code: c.course_code || c.course_name,
      name: c.course_code ? c.course_name : "",
      color: c.color || COURSE_PALETTE[seen.size % COURSE_PALETTE.length],
    });
  }
  return [...seen.values()];
}

export function fileFormat(fileName: string): string {
  const m = /\.([a-z0-9]+)$/i.exec(fileName || "");
  const ext = m ? m[1].toUpperCase() : "";
  if (ext === "PPT") return "PPTX";
  if (ext === "DOC") return "DOCX";
  return ext || "FILE";
}

export function displayTitle(fileName: string): string {
  return (fileName || "").replace(/\.(pdf|docx?|pptx?)$/i, "") || fileName || "Untitled";
}

export function addedLabel(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

export function uniqueName(base: string, names: string[]): string {
  if (!names.includes(base)) return base;
  let i = 2;
  while (names.includes(`${base} ${i}`)) i++;
  return `${base} ${i}`;
}

export function highlight(s: string, q: string): { a: string; m: string; b: string } {
  const i = q ? s.toLowerCase().indexOf(q) : -1;
  return i < 0 ? { a: s, m: "", b: "" } : { a: s.slice(0, i), m: s.slice(i, i + q.length), b: s.slice(i + q.length) };
}

function firstSentence(text: string): string {
  const plain = text.replace(/[*_`#>]/g, "").replace(/\s+/g, " ").trim();
  const m = /^(.{1,140}?[.!?])(\s|$)/.exec(plain);
  return m ? m[1] : plain.slice(0, 120);
}

/**
 * The "first page" card. There is no stored page image or file, so the card is
 * rendered from what the document does have: its lead concept and the opening
 * sentences of its extracted notes (falling back to the summary).
 */
export function pageOf(doc: Doc): { h: string; lines: string[] } {
  const notes = doc.concept_notes || [];
  if (notes.length) {
    return {
      h: notes[0].name,
      lines: notes.slice(0, 2).map((n) => firstSentence(n.description || n.name)).filter(Boolean),
    };
  }
  const sentences = (doc.summary || "").match(/[^.!?]+[.!?]+/g) || (doc.summary ? [doc.summary] : []);
  return { h: displayTitle(doc.file_name), lines: sentences.slice(0, 2).map((s) => s.trim()) };
}

export function matchesQuery(doc: Doc, q: string, course?: CourseInfo): boolean {
  if (!q) return true;
  return (
    displayTitle(doc.file_name).toLowerCase().includes(q) ||
    (doc.summary || "").toLowerCase().includes(q) ||
    (doc.concept_notes || []).some((c) => c.name.toLowerCase().includes(q)) ||
    (course ? course.code.toLowerCase().includes(q) : false)
  );
}

export function sortDocs(list: Doc[], sort: SortKey, courseCode: (d: Doc) => string): Doc[] {
  const t = (d: Doc) => new Date(d.created_at).getTime() || 0;
  return [...list].sort((a, b) => {
    switch (sort) {
      case "oldest": return t(a) - t(b);
      case "name": return displayTitle(a.file_name).localeCompare(displayTitle(b.file_name));
      case "type": return typeOf(a.category).label.localeCompare(typeOf(b.category).label) || t(b) - t(a);
      case "course": return (courseCode(a) || "~").localeCompare(courseCode(b) || "~") || t(b) - t(a);
      default: return t(b) - t(a);
    }
  });
}
