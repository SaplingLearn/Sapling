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
 * list of its own to maintain (unlike /flashcards: see `flashcardsHref`).
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

/** The Flashcards link's concept selection: `concepts=A|B`. */
export const CONCEPTS_PARAM = "concepts";

/**
 * Concept names as one `concepts=` value: joined with "|". A "|" or a "\"
 * INSIDE a name is written with a "\" before it, so the list reads back
 * exactly (a name may hold either; "&", "," and "%" are the URL encoding's
 * to carry). A name with neither is written as it always was, so links made
 * before the escape still read the same.
 */
export function encodeConcepts(names: string[]): string {
  return names.map(name => name.replace(/[\\|]/g, "\\$&")).join("|");
}

/** The names in a `concepts=` value (see `encodeConcepts`), trimmed, blanks dropped. */
export function decodeConcepts(value: string | null | undefined): string[] {
  const text = value ?? "";
  const names: string[] = [];
  let name = "";
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    const next = text[i + 1];
    if (ch === "\\" && (next === "|" || next === "\\")) {
      // An escaped "|" or "\": part of the name.
      name += next;
      i++;
    } else if (ch === "|") {
      names.push(name);
      name = "";
    } else {
      name += ch;
    }
  }
  names.push(name);
  return names.map(x => x.trim()).filter(Boolean);
}

/** Flashcards, optionally seeded with a course and a concept selection;
 *  `start` asks the page to begin (see `START_PARAM`).
 *
 *  /flashcards is NOT under /study, so nothing comes with the prefix: it is
 *  auth-gated by its own entry in lib/appRoutes.ts SHELL_PREFIXES (and the
 *  middleware matcher), flag-gated (hide_study) by lib/navFeatures.ts
 *  NAV_PATH_ALIASES, and keeps Study lit through `STUDY_TOOL_PATHS` below. */
export function flashcardsHref(
  courseId?: string | null,
  concepts: string[] = [],
  opts: { start?: boolean } = {},
): string {
  const p = new URLSearchParams();
  if (courseId) p.set("course", courseId);
  if (concepts.length) p.set(CONCEPTS_PARAM, encodeConcepts(concepts));
  if (opts.start) p.set(START_PARAM, "1");
  return p.size ? `/flashcards?${p.toString()}` : "/flashcards";
}

/**
 * The live URL still asks to start. A tool reads this rather than only the
 * params it parsed on arrival: closing a quiz remounts its home, and a stale
 * `start` there would start it again, so it could never be left.
 *
 * Only for an EFFECT (or an event handler), never for a render. On a
 * client-side navigation the page renders BEFORE the router writes its URL to
 * the address bar, so during that first render the live URL is still the page
 * being left and says nothing about this one: Flashcards read it there and
 * took the hub's `start=1` link for one that did not ask to start. A render
 * reads the router's params (`useSearchParams`), which `consumeStartParam`
 * keeps true.
 */
export function startStillRequested(): boolean {
  if (typeof window === "undefined") return false;
  return new URL(window.location.href).searchParams.get(START_PARAM) === "1";
}

/**
 * Change the current URL's query in place, with no navigation, and tell the
 * router: a NEW history entry when `push`, else the current one rewritten.
 *
 * The state argument must be null. Next patches `history.pushState` /
 * `replaceState` so that a URL edited this way reaches `useSearchParams`, but
 * it skips its own hook when handed the state it wrote itself (`__NA`), and
 * `window.history.state` is exactly that: the address bar changes while the
 * router keeps the old URL. Two things then go wrong. A page that renders
 * again from the router's params sees a `start` that was already acted on;
 * and the router writes ITS url back over the address bar on its next state
 * change, undoing the edit. Nothing is lost by passing null: Next copies its
 * own state onto the entry. (lib/quiz/useQuizSession.ts `goTo` documents the
 * same trap.)
 */
export function editUrlInPlace(url: URL, how: "push" | "replace" = "replace"): void {
  if (how === "push") window.history.pushState(null, "", url.toString());
  else window.history.replaceState(null, "", url.toString());
}

/** Drop `START_PARAM` from the current URL without a navigation. */
export function consumeStartParam(): void {
  if (typeof window === "undefined") return;
  const url = new URL(window.location.href);
  if (!url.searchParams.has(START_PARAM)) return;
  url.searchParams.delete(START_PARAM);
  editUrlInPlace(url);
}

/** Pages that are Study tools rather than destinations of their own: the nav
 *  keeps Study selected while a student is in one of them. This is selection
 *  only; which flag hides each page is lib/navFeatures.ts (Quiz has its own,
 *  hide_quiz; Flashcards follows Study through NAV_PATH_ALIASES). */
export const STUDY_TOOL_PATHS = ["/quiz", "/flashcards"];
