/**
 * The Study Guides home's rules, as pure functions: which guides a search
 * keeps, the order a sort puts them in, and the words on a card.
 */
import type { GuideCard, GuideStatus } from "@/lib/studyGuide/types";

export type SortKey = "recent" | "oldest" | "class";

export const SORTS: { key: SortKey; label: string }[] = [
  { key: "recent", label: "Most recent" },
  { key: "oldest", label: "Oldest" },
  { key: "class", label: "Class" },
];

export const sortLabel = (key: SortKey): string =>
  SORTS.find(sort => sort.key === key)?.label ?? "";

/** When the guide was written. One still being written has only its row's date. */
export const guideDate = (guide: GuideCard): string => guide.generated_at ?? guide.created_at;

const time = (guide: GuideCard): number => Date.parse(guideDate(guide)) || 0;

/** The guides whose title, class (name or code) or scope label has the query in it. */
export function searchGuides(guides: GuideCard[], query: string): GuideCard[] {
  const q = query.trim().toLowerCase();
  if (!q) return guides;
  return guides.filter(guide =>
    [guide.title, guide.course_name, guide.course_code, guide.scope_label].some(text => text.toLowerCase().includes(q)),
  );
}

/** A sorted copy. "Class" groups by the class code a card shows, newest first inside a class. */
export function sortGuides(guides: GuideCard[], sort: SortKey): GuideCard[] {
  const newestFirst = (a: GuideCard, b: GuideCard) => time(b) - time(a);
  const order: Record<SortKey, (a: GuideCard, b: GuideCard) => number> = {
    recent: newestFirst,
    oldest: (a, b) => time(a) - time(b),
    class: (a, b) => a.course_code.localeCompare(b.course_code) || newestFirst(a, b),
  };
  return [...guides].sort(order[sort]);
}

/** "Today" or "Nov 3", with the year once it is not this one. */
export function dateText(guide: GuideCard, now: Date): string {
  const when = new Date(guideDate(guide));
  if (Number.isNaN(when.getTime())) return "";
  if (when.toDateString() === now.toDateString()) return "Today";
  const year = when.getFullYear() === now.getFullYear() ? undefined : "numeric";
  return when.toLocaleDateString("en-US", { month: "short", day: "numeric", year });
}

/**
 * What a guide that is not ready says in its place. A `generating` guide is
 * only written while a reader has it open, so the card does not claim it is
 * being written now. Opening it resumes the writing.
 */
export function statusText(status: GuideStatus): string {
  if (status === "generating") return "Not finished";
  return status === "failed" ? "Could not finish" : "";
}

/**
 * The saved guides the Library shows under its course filter and search. A
 * guide always belongs to a class, so "Uncategorized" has none.
 */
export function libraryGuides(guides: GuideCard[], courseFilter: string, query: string): GuideCard[] {
  if (courseFilter === "uncategorized") return [];
  const saved = guides.filter(guide => guide.saved_at !== null);
  const inCourse = courseFilter === "all" ? saved : saved.filter(guide => guide.course_id === courseFilter);
  return searchGuides(inCourse, query);
}
