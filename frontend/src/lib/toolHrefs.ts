/**
 * Where the Study tools live, in one place.
 *
 * Study guides moved into the Library: the hub's Study Guide button opens the
 * course's study-guide documents rather than the retired `?mode=guide` pane.
 * Flashcards and Quiz have had pages of their own all along — these builders
 * are what keep the hub, the Dashboard, the tool nav and the `?mode=`
 * redirects pointing at the same URLs.
 */

/** The Library, optionally narrowed to one course, one document type, and/or
 *  a search (which matches titles, summaries AND linked concept names). */
export function libraryHref(courseId?: string | null, type?: string, query?: string): string {
  const p = new URLSearchParams();
  if (courseId) p.set("course", courseId);
  if (type) p.set("type", type);
  if (query) p.set("q", query);
  return p.size ? `/library?${p.toString()}` : "/library";
}

/**
 * Where "Study Guide" goes.
 *
 * For ONE concept, search the course's material for it rather than filtering
 * to the study_guide type: the type filter answers "which of my uploads are
 * study guides", which on a course without one is an empty shelf and a dead
 * end. The search matches linked concept names, so this lands on the material
 * that actually covers the concept, whatever type it was filed under.
 */
export function studyGuideHref(courseId?: string | null, concept?: string): string {
  return concept ? libraryHref(courseId, undefined, concept) : libraryHref(courseId, "study_guide");
}

/** Flashcards, optionally seeded with a course and a concept selection. */
export function flashcardsHref(courseId?: string | null, concepts: string[] = []): string {
  const p = new URLSearchParams();
  if (courseId) p.set("course", courseId);
  if (concepts.length) p.set("concepts", concepts.join("|"));
  return p.size ? `/flashcards?${p.toString()}` : "/flashcards";
}

/** Pages that are Study tools rather than destinations of their own: the nav
 *  keeps Study selected while a student is in one of them. */
export const STUDY_TOOL_PATHS = ["/quiz", "/flashcards"];
