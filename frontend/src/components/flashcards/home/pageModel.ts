/**
 * Pure rules of the Flashcards PAGE (screens/Flashcards.tsx): what the URL
 * asked for on arrival, which of the page's states is showing, and what the
 * header says about it. The page's state and effects are in
 * useFlashcardsPage.ts; the home's and the builder's own rules are in
 * flashcardsModel.ts and decksModel.ts.
 */
import type { EnrolledCourse } from "@/lib/api";
import { CONCEPTS_PARAM, START_PARAM, decodeConcepts } from "@/lib/toolHrefs";
import { REVIEW_PARAM } from "../review/reviewSession";
import { BUILD_PARAM } from "./buildSession";
import type { Card, Draft } from "./flashcardsModel";

// ── arrival ──────────────────────────────────────────────────────────────────

/** What the URL asked for on arrival. */
export interface Arrival {
  /** "" when the link names no course. */
  courseId: string;
  concepts: string[];
  /** `start=1`: go straight into the review of `concepts` (see toolHrefs). */
  start: boolean;
  /** A reload inside a review (reviewSession.ts). */
  review: boolean;
  /** A reload inside the set builder (buildSession.ts). */
  build: boolean;
}

/**
 * `params` are the ROUTER's (`useSearchParams`), and nothing else is asked.
 * They are the URL this render is for, on a reload and on a client-side
 * navigation alike; the address bar is not, until the router has written to
 * it, which is after the page's first render. (`start` used to be checked
 * against the address bar as well, so the hub's `start=1` link, followed by a
 * click, read as a link that did not ask to start and opened the builder.)
 * The router's params stay true after the page edits its own URL, because
 * those edits are made through it (toolHrefs `editUrlInPlace`): a `start`
 * that was acted on is gone from them too.
 */
export function parseArrival(params: Pick<URLSearchParams, "get">): Arrival {
  return {
    courseId: params.get("course") || "",
    concepts: decodeConcepts(params.get(CONCEPTS_PARAM)),
    start: params.get(START_PARAM) === "1",
    review: params.get(REVIEW_PARAM) === "1",
    build: params.get(BUILD_PARAM) === "1",
  };
}

/** A link that names concepts without `start` opens the builder on them. */
export const opensBuilder = (arrival: Arrival): boolean => arrival.concepts.length > 0 && !arrival.start;

/**
 * A `start=1` link that must not start anything: it names no concept, the
 * deck could not be read, or its course is not one of the student's (the page
 * fell back to another, whose concepts these are not). The home opens
 * instead, and nothing is generated.
 */
export function startBlocked(arrival: Arrival, courseId: string, cardsFailed: boolean): boolean {
  const elsewhere = !!arrival.courseId && arrival.courseId !== courseId;
  return !arrival.concepts.length || cardsFailed || elsewhere;
}

/** What the page's reads have come to. */
export interface PageLoads {
  /** The card list has answered for this term (or failed). */
  cardsLoaded: boolean;
  cardsLoading: boolean;
  cardsFailed: boolean;
  /** The (term-scoped) course list is final. */
  coursesReady: boolean;
  coursesFailed: boolean;
  mapReady: boolean;
  setsSettled: boolean;
}

/** What each of the page's waits is waiting on, and what the reload markers
 *  on the URL may still ask for (`start=1` outranks both). */
export function pageGates(arrival: Arrival, loads: PageLoads) {
  const cardsAnswered = loads.cardsLoaded && !loads.cardsLoading;
  return {
    /** `start=1` may act. A link that names no course starts by name alone,
     *  without the course list. */
    start: cardsAnswered && (!arrival.courseId || loads.coursesReady),
    /** A reload's review may be read back. It is kept under the course it was
     *  started on, so this waits for the course list (the URL need not name
     *  the course) and for a card list that was really read: a failed one
     *  would find none of its cards and the review would be forgotten. */
    restoreReview: cardsAnswered && loads.coursesReady && !loads.cardsFailed,
    /** Every read the home waits on has answered. */
    home: loads.coursesReady && loads.cardsLoaded && loads.mapReady && loads.setsSettled,
    /** A list the page cannot do without could not be read. */
    failed: loads.cardsFailed || loads.coursesFailed,
    wantsReview: arrival.review && !arrival.start,
    wantsBuild: arrival.build && !arrival.start,
  };
}

// ── the course ───────────────────────────────────────────────────────────────

/** The course's short name as the page shows it: its code, else its name. */
export const courseLabel = (course: EnrolledCourse | undefined): string =>
  (course ? course.course_code || course.course_name : "");

/** The review card's accent: the course's colour, else the brand's. */
export const courseAccent = (course: EnrolledCourse | undefined): string =>
  course?.color || "var(--brand-forest)";

// ── which state is showing ───────────────────────────────────────────────────

/** Where a review was started from: a deck on the home, the builder's Start,
 *  or the URL's `start=1`. */
export type ReviewFrom = "home" | "build" | "link";

export interface OpenReview {
  deck: Card[];
  title: string;
  from: ReviewFrom;
}

/** BUILD is open (over the home); `note` is what a sort said on the way in. */
export interface OpenBuild {
  note: string;
}

/** Which of the page's states is showing, with what that state is of. */
export type View =
  | { kind: "review"; review: OpenReview }
  | { kind: "build"; build: OpenBuild }
  | { kind: "failed" | "arriving" | "loading" | "home" };

export function pageView(is: {
  review: OpenReview | null;
  /** The card list or the course list could not be read. */
  failed: boolean;
  /** A `start=1` run, or a reload's review being read back. */
  arriving: boolean;
  /** Every read the home waits on has answered. */
  ready: boolean;
  build: OpenBuild | null;
}): View {
  if (is.review) return { kind: "review", review: is.review };
  // Before "arriving": a reload's review that is waiting on a list that could
  // not be read says so, and the retry lets it come back.
  if (is.failed) return { kind: "failed" };
  if (is.arriving) return { kind: "arriving" };
  if (!is.ready) return { kind: "loading" };
  return is.build ? { kind: "build", build: is.build } : { kind: "home" };
}

// ── the header ───────────────────────────────────────────────────────────────

/** What the header shows where the course field is on the home, and the way
 *  back that replaces Import. null: the home (course field, Import). */
export interface Place {
  /** What is being reviewed or built. */
  label: string;
  back: string;
  backLabel?: string;
}

export function headerPlace(view: View, draft: Pick<Draft, "setId" | "givenName">): Place | null {
  if (view.kind === "review") {
    return view.review.from === "build"
      ? { label: view.review.title, back: "Back", backLabel: "Back to your selection" }
      : { label: view.review.title, back: "All sets" };
  }
  if (view.kind === "build") return { label: draft.setId ? draft.givenName || "Edit set" : "New set", back: "All sets" };
  return null;
}

/** The topic the Import dialog opens on: the one concept ticked, when it is one. */
export const importTopic = (draft: Pick<Draft, "selected">): string =>
  (draft.selected.length === 1 ? draft.selected[0] : "");
