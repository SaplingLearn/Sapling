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

/**
 * The deep-link marker for "START this, don't just open the tool" (the Study
 * hub's Quiz / Flashcards buttons). /quiz starts the named concept or course
 * queue; /flashcards generates cards when the named deck is empty. Each page
 * drops it from the URL once it has acted (`consumeStartParam`), so a reload
 * or a Back into the page never starts a second session.
 */
export const START_PARAM = "start";

/** Flashcards, optionally seeded with a course and a concept selection;
 *  `start` asks the page to begin (see `START_PARAM`). */
export function flashcardsHref(
  courseId?: string | null,
  concepts: string[] = [],
  opts: { start?: boolean } = {},
): string {
  const p = new URLSearchParams();
  if (courseId) p.set("course", courseId);
  if (concepts.length) p.set("concepts", concepts.join("|"));
  if (opts.start) p.set(START_PARAM, "1");
  return p.size ? `/flashcards?${p.toString()}` : "/flashcards";
}

/** The live URL still asks to start. A tool reads this rather than only the
 *  params it parsed on arrival: closing a quiz (or a deck) remounts its home,
 *  and a stale `start` there would start it again, so it could never be left. */
export function startStillRequested(): boolean {
  if (typeof window === "undefined") return false;
  return new URL(window.location.href).searchParams.get(START_PARAM) === "1";
}

/** Drop `START_PARAM` from the current URL without a navigation. */
export function consumeStartParam(): void {
  if (typeof window === "undefined") return;
  const url = new URL(window.location.href);
  if (!url.searchParams.has(START_PARAM)) return;
  url.searchParams.delete(START_PARAM);
  window.history.replaceState(window.history.state, "", url.toString());
}

/** Pages that are Study tools rather than destinations of their own: the nav
 *  keeps Study selected while a student is in one of them. */
export const STUDY_TOOL_PATHS = ["/quiz", "/flashcards"];
