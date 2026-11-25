/**
 * The Library's pure logic: the design's lookup tables, and the filter → sort
 * pipeline its `renderVals()` runs on every keystroke.
 *
 * Kept out of the component so the behaviour the design specifies (which
 * documents a scope shows, what a search matches, how each sort orders, how an
 * untitled item is deduped) can be read and tested without a DOM.
 *
 * Every literal here — label, hex, order — is the design handoff's own.
 */
import type { Document as Doc, DocFolder } from "@/lib/types";
import type { EnrolledCourse } from "@/lib/api";

/** A document's type chip: the design's label and its dot colour. */
export const TYPES: Record<Doc["category"], { label: string; color: string }> = {
  lecture_notes: { label: "Lecture Notes", color: "#6E8B4E" },
  slides:        { label: "Slides",        color: "#B8873F" },
  reading:       { label: "Reading",       color: "#7A4A78" },
  study_guide:   { label: "Study Guide",   color: "#3E7F7A" },
  assignment:    { label: "Assignment",    color: "#B4562C" },
  syllabus:      { label: "Syllabus",      color: "#3F3B31" },
  other:         { label: "Other",         color: "#8A8372" },
};

/** The order the Type menu lists them in, after "All Types". */
export const TYPE_ORDER: Doc["category"][] = [
  "lecture_notes", "slides", "reading", "study_guide", "assignment", "syllabus", "other",
];

/** File-format colours, used for both the tile and the corner tag. */
export const FMT: Record<string, string> = {
  PDF: "#B4562C",
  PPTX: "#B8873F",
  DOCX: "#3E6E9E",
};

/** The fallback for a format the design has no colour for. */
export const FMT_FALLBACK = "#8A8372";

export type SortKey = "recent" | "oldest" | "name" | "course" | "type" | "pages";

export const SORTS: [SortKey, string][] = [
  ["recent", "Recently Added"],
  ["oldest", "Oldest First"],
  ["name", "Name A–Z"],
  ["course", "Course"],
  ["type", "Type"],
  ["pages", "Most Pages"],
];

/**
 * A location in the Library: everything, one course (`c:<id>`, or `c:none` for
 * documents with no course), one folder (`f:<id>`), or the Trash.
 */
export type Loc = "all" | "trash" | `c:${string}` | `f:${string}`;

export function parseLoc(loc: Loc): { kind: "all" | "trash" | "c" | "f"; id: string | null } {
  if (loc === "all" || loc === "trash") return { kind: loc, id: null };
  const [k, ...rest] = loc.split(":");
  return { kind: k === "c" ? "c" : "f", id: rest.join(":") };
}

/** The format tag a document shows, read off its file name. */
export function fmtOf(doc: Doc): string {
  const ext = (doc.file_name.split(".").pop() || "").toUpperCase();
  return ext && ext.length <= 4 && ext !== doc.file_name.toUpperCase() ? ext : "PDF";
}

/** The title the Library shows: the file name without its extension. */
export function titleOf(doc: Doc): string {
  return doc.file_name.replace(/\.[^.]+$/, "") || doc.file_name;
}

/**
 * The compact date the rows show ("Nov 5"), or this year's day/month for an
 * older one. The design's mock data is a bare "Nov 5"; a real library spans
 * years, so a document from another year keeps its year.
 */
export function addedLabel(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  const now = new Date();
  return d.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    ...(d.getFullYear() === now.getFullYear() ? {} : { year: "numeric" }),
  });
}

/** Sort key for "Recently Added" / "Oldest First". */
export function timeOf(doc: Doc): number {
  const t = new Date(doc.created_at).getTime();
  return Number.isNaN(t) ? 0 : t;
}

/**
 * Split `s` around the first case-insensitive occurrence of `q`, so the row can
 * wrap the middle in a `<mark>`. Returns the whole string as `a` when there is
 * no match.
 */
export function highlight(s: string, q: string): { a: string; m: string; b: string } {
  const i = q ? s.toLowerCase().indexOf(q) : -1;
  if (i < 0) return { a: s, m: "", b: "" };
  return { a: s.slice(0, i), m: s.slice(i, i + q.length), b: s.slice(i + q.length) };
}

/**
 * `base`, or the first "base N" that is not taken — how the design names a
 * second "New Folder".
 */
export function uniqueName(base: string, taken: string[]): string {
  if (!taken.includes(base)) return base;
  let i = 2;
  while (taken.includes(`${base} ${i}`)) i += 1;
  return `${base} ${i}`;
}

/**
 * One row per abstract course (#449): the graph API returns one row per
 * ENROLLMENT, so a course with two offerings arrives twice. The first
 * enrollment's row is the stable representative — this is the same dedupe the
 * old Library did, moved here so the new one and its tests share it.
 */
export function dedupeCourses(courses: EnrolledCourse[]): EnrolledCourse[] {
  const byId = new Map<string, EnrolledCourse>();
  for (const c of courses) if (!byId.has(c.course_id)) byId.set(c.course_id, c);
  return [...byId.values()];
}

/** The short label a course shows on a chip or a dot ("MATH210"). */
export function courseLabel(c: EnrolledCourse): string {
  return c.course_code || c.course_name;
}

export interface FilterInput {
  docs: Doc[];
  loc: Loc;
  /** The search box, already trimmed and lowercased. */
  q: string;
  type: Doc["category"] | "all";
  sort: SortKey;
  folders: DocFolder[];
  courses: EnrolledCourse[];
}

/**
 * Everything the list needs, in the order the design computes it:
 *
 *  - `scoped` is the location + search filter, BEFORE the type filter. The
 *    Type menu's per-type counts are taken from it, so they say how many of
 *    each type the current scope holds rather than how many survive the type
 *    that is already chosen.
 *  - `list` applies the type filter and the sort.
 *
 * A course root (a course with no search running) hides documents that are
 * inside one of its folders — they show as the folder, not twice.
 */
export function filterDocuments({
  docs, loc, q, type, sort, folders, courses,
}: FilterInput): { scoped: Doc[]; list: Doc[] } {
  const { kind, id } = parseLoc(loc);
  const courseRoot = kind === "c" && !q;

  const inLoc = (d: Doc): boolean => {
    if (kind === "all" || kind === "trash") return true;
    if (kind === "c") {
      const matches = id === "none" ? !d.course_id : d.course_id === id;
      return matches && (!courseRoot || !d.folder_id);
    }
    return d.folder_id === id;
  };

  const courseById = new Map(courses.map(c => [c.course_id, c]));
  const matchQ = (d: Doc): boolean => {
    if (!q) return true;
    if (titleOf(d).toLowerCase().includes(q)) return true;
    if ((d.summary || "").toLowerCase().includes(q)) return true;
    if ((d.concept_notes || []).some(c => c.name.toLowerCase().includes(q))) return true;
    const c = d.course_id ? courseById.get(d.course_id) : undefined;
    return !!c && courseLabel(c).toLowerCase().includes(q);
  };

  const scoped = docs.filter(d => inLoc(d) && matchQ(d));
  const list = scoped.filter(d => type === "all" || d.category === type);

  // The prototype sorts course-less documents last with a "~" sentinel, which
  // only works under ASCII ordering — `localeCompare` uses ICU collation,
  // where "~" sorts BEFORE every letter. The rule is stated instead.
  const byCourse = (a: Doc, b: Doc) => {
    const ca = a.course_id ? courseById.get(a.course_id) : undefined;
    const cb = b.course_id ? courseById.get(b.course_id) : undefined;
    if (!ca || !cb) return (ca ? 0 : 1) - (cb ? 0 : 1);
    return courseLabel(ca).localeCompare(courseLabel(cb));
  };
  const sorted = [...list].sort((a, b) => {
    switch (sort) {
      case "oldest": return timeOf(a) - timeOf(b);
      case "name":   return titleOf(a).localeCompare(titleOf(b));
      case "type":   return TYPES[a.category].label.localeCompare(TYPES[b.category].label)
                          || timeOf(b) - timeOf(a);
      // A null page count is unknown, not zero: those sort last, then by date.
      case "pages":  return (b.page_count ?? -1) - (a.page_count ?? -1) || timeOf(b) - timeOf(a);
      case "course": return byCourse(a, b) || timeOf(b) - timeOf(a);
      default:       return timeOf(b) - timeOf(a);
    }
  });

  void folders;
  return { scoped, list: sorted };
}

/** The folders shown as rows: a course's own, and only at that course's root. */
export function foldersAtLoc(folders: DocFolder[], loc: Loc, q: string): DocFolder[] {
  const { kind, id } = parseLoc(loc);
  if (kind !== "c" || q) return [];
  const courseId = id === "none" ? null : id;
  return folders.filter(f => (f.course_id || null) === courseId);
}
