/**
 * Where the Study tools live, in one place.
 *
 * Study Guide, Flashcards and Quiz are pages of their own, opened from the
 * Study hub (the retired `?mode=guide` / `?mode=cards` panes redirect to
 * them) — these builders
 * are what keep the hub, the Dashboard and the `?mode=` redirects pointing
 * at the same URLs.
 */

/** The Study hub, optionally opened on one course. The tools' back buttons use
 *  this, so leaving a tool returns to the course it was opened from rather
 *  than to whichever course the hub lists first. */
export function studyHref(courseId?: string | null): string {
  return courseId ? `/study?course=${encodeURIComponent(courseId)}` : "/study";
}

/**
 * Where "Study Guide" goes: the Study Guide page (/study/guide), opened on
 * the course, and on the exam when one is selected. Under /study, so it is
 * auth-gated, flag-gated (hide_study) and keeps Study lit in the nav with no
 * list of its own to maintain.
 */
export function studyGuideHref(courseId?: string | null, examId?: string | null): string {
  const p = new URLSearchParams();
  if (courseId) p.set("course", courseId);
  if (examId) p.set("exam", examId);
  return p.size ? `/study/guide?${p.toString()}` : "/study/guide";
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
