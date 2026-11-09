/**
 * Where the Study tools live, in one place.
 *
 * Study guides moved into the Library: the hub's Study Guide button opens the
 * course's study-guide documents rather than the retired `?mode=guide` pane.
 * Flashcards and Quiz have had pages of their own all along — these builders
 * are what keep the hub, the Dashboard, the tool nav and the `?mode=`
 * redirects pointing at the same URLs.
 */

/** The Library, optionally narrowed to one course and/or one document type. */
export function libraryHref(courseId?: string | null, type?: string): string {
  const p = new URLSearchParams();
  if (courseId) p.set("course", courseId);
  if (type) p.set("type", type);
  return p.size ? `/library?${p.toString()}` : "/library";
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
