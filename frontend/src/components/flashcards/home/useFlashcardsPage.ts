"use client";
/**
 * The Flashcards page's state: which course it is on, what it has loaded, and
 * which of its states (home, builder, review) is open. screens/Flashcards.tsx
 * renders what this returns; the rules are pure functions in pageModel.ts.
 *
 * One hook per concern, composed by `useFlashcardsPage` at the bottom:
 *
 *   useTermCourses ..... the student's courses, scoped to the active term
 *   useArrival ......... what the URL asked for, read once
 *   useCourse .......... the course the page is on
 *   usePageData ........ the page's reads, the builder's draft, the home model
 *   useOpenReview ...... the open review, and what leaving it refreshes
 *   useStarts .......... starting a review: from the builder, a deck, the link
 *   useStartOnArrival .. the `start=1` deep link, acted on once
 */
import React from "react";
import { useSearchParams } from "next/navigation";
import { useUser } from "@/context/UserContext";
import { getCourses, type EnrolledCourse } from "@/lib/api";
import { consumeStartParam, startStillRequested } from "@/lib/toolHrefs";
import { courseInTerm, useActiveSemester } from "@/lib/useActiveSemester";
import { useLatestRequest } from "@/lib/useLatestRequest";
import { useReviewSession } from "../review/reviewSession";
import { useBuildSession } from "./buildSession";
import { namesInSets } from "./decksModel";
import {
  deckTitle,
  draftReducer,
  emptyDraft,
  homeModel,
  orderNames,
  shuffled,
  type Card,
} from "./flashcardsModel";
import {
  courseAccent,
  courseLabel,
  headerPlace,
  importTopic,
  opensBuilder,
  pageGates,
  pageView,
  parseArrival,
  startBlocked,
  type Arrival,
  type OpenBuild,
  type OpenReview,
  type ReviewFrom,
} from "./pageModel";
import { useCards, useCourseConcepts, useCourseExams, useFlashcardSets } from "./useFlashcardsData";
import { useStart, type StartPlan } from "./useStart";

// ── the student's courses ────────────────────────────────────────────────────

export interface TermCourses {
  /** The student's courses in the active term (all of them when there is none). */
  courses: EnrolledCourse[];
  /** The (term-scoped) list is final: an empty one now means "no courses". */
  coursesReady: boolean;
  /** The list could not be read: `courses` is not the student's real list. */
  coursesFailed: boolean;
  reloadCourses: () => void;
  // "" = All semesters (unscoped); fetches gate on semesterReady so a stored
  // term never double-fetches (#141).
  semester: string;
  semesterReady: boolean;
}

/** The page loads the courses itself and scopes them to the active term. */
export function useTermCourses(): TermCourses {
  const { userId, userReady } = useUser();
  const [semester, , semesterReady] = useActiveSemester();
  const [all, setAll] = React.useState<EnrolledCourse[]>([]);
  const [status, setStatus] = React.useState<"loading" | "ready" | "failed">("loading");
  const req = useLatestRequest();

  const reloadCourses = React.useCallback(() => {
    if (!userReady || !userId) return;
    const run = req.begin();
    setStatus("loading");
    getCourses(userId)
      .then(r => {
        if (!run.isCurrent()) return;
        setAll(r.courses || []);
        setStatus("ready");
      })
      .catch(err => {
        if (!run.isCurrent()) return;
        console.error("flashcards courses load failed", err);
        setStatus("failed");
      });
  }, [userReady, userId, req]);

  React.useEffect(() => {
    reloadCourses();
    return req.cancel;
  }, [reloadCourses, req]);

  const courses = React.useMemo(
    () => (semester ? all.filter(c => courseInTerm(c, semester)) : all),
    [all, semester],
  );
  return {
    courses,
    coursesReady: status === "ready" && semesterReady,
    coursesFailed: status === "failed",
    reloadCourses,
    semester,
    semesterReady,
  };
}

// ── the URL, and the course ──────────────────────────────────────────────────

/** What the URL asked for on arrival. Read once: it seeds the page. */
function useArrival(): Arrival {
  const searchParams = useSearchParams();
  const [arrival] = React.useState(() => parseArrival(searchParams, startStillRequested()));
  return arrival;
}

/**
 * The course the page is on: the one picked (or named in the URL), else the
 * first. There is no "all courses" here, because the concept map is one
 * course's. Until the list is in, the URL's id stands, so its reads can start.
 */
function useCourse(courses: EnrolledCourse[], coursesReady: boolean, initialId: string) {
  const [picked, setPicked] = React.useState(initialId);
  const fallback = coursesReady ? courses[0] : undefined;
  const course = courses.find(c => c.course_id === picked) ?? fallback;
  const pending = coursesReady ? "" : picked;
  return { course, courseId: course ? course.course_id : pending, pick: setPicked };
}

/** Runs `onSwitch` when the page moves from one course to another (not when
 *  the first one arrives). */
function useOnCourseSwitch(courseId: string, onSwitch: () => void) {
  const last = React.useRef(courseId);
  const run = React.useRef(onSwitch);
  React.useEffect(() => { run.current = onSwitch; });
  React.useEffect(() => {
    const left = last.current;
    last.current = courseId;
    if (left && left !== courseId) run.current();
  }, [courseId]);
}

// ── what the page has loaded ─────────────────────────────────────────────────

interface DataInput {
  userId: string;
  courseId: string;
  courseName?: string;
  semester: string;
  semesterReady: boolean;
  now?: Date;
  /** The concepts the URL named: the draft starts with them ticked. */
  concepts: string[];
}

function usePageData({ userId, courseId, courseName, semester, semesterReady, now, concepts }: DataInput) {
  const today = React.useMemo(() => now ?? new Date(), [now]);
  const cards = useCards(userId, semester, semesterReady, now);
  const map = useCourseConcepts(userId, courseId, semester, semesterReady, today);
  const exams = useCourseExams(userId, courseId);
  const sets = useFlashcardSets(userId, courseId);
  const [draft, dispatch] = React.useReducer(draftReducer, concepts, emptyDraft);
  const inSets = React.useMemo(() => namesInSets(sets.sets), [sets.sets]);
  const model = React.useMemo(
    () => homeModel({ cards: cards.cards, courseId, courseName, concepts: map.concepts, custom: draft.custom, known: inSets, now: cards.now }),
    [cards.cards, cards.now, courseId, courseName, map.concepts, draft.custom, inSets],
  );
  const conceptNames = React.useMemo(() => map.concepts.map(c => c.name), [map.concepts]);
  return { today, cards, map, exams, sets, draft, dispatch, model, conceptNames };
}

type PageData = ReturnType<typeof usePageData>;

// ── the open review ──────────────────────────────────────────────────────────

function useOpenReview(reloadCards: () => Promise<unknown>) {
  const [review, setReview] = React.useState<OpenReview | null>(null);
  /** A rating was saved in the review: the home's due counts are stale. */
  const reviewed = React.useRef(false);
  const markReviewed = React.useCallback(() => { reviewed.current = true; }, []);

  // A review started in the builder returns to it (the selection is still
  // there); any other returns to the home.
  const leaveReview = () => {
    setReview(null);
    if (!reviewed.current) return;
    reviewed.current = false;
    void reloadCards();
  };

  const removeFromDeck = (cardId: string) => {
    setReview(prev => (prev ? { ...prev, deck: prev.deck.filter(c => c.id !== cardId) } : prev));
    void reloadCards();
  };

  return { review, setReview, markReviewed, leaveReview, removeFromDeck };
}

// ── starting a review ────────────────────────────────────────────────────────

interface StartsInput {
  userId: string;
  courseId: string;
  courseName?: string;
  semester: string;
  random: () => number;
  data: PageData;
  onReview: (review: OpenReview) => void;
}

function useStarts({ userId, courseId, courseName, semester, random, data, onReview }: StartsInput) {
  const { cards, conceptNames, draft, model } = data;
  /** The deck on the home a review is being started from. */
  const [playing, setPlaying] = React.useState<string | null>(null);
  /** Where the run in flight was asked from. */
  const origin = React.useRef<ReviewFrom>("home");
  const onDeck = React.useCallback(
    (deck: Card[], title: string) => onReview({ deck, title, from: origin.current }),
    [onReview],
  );
  const starter = useStart({ userId, courseId, courseName, semester, cards, conceptNames, random, onDeck });
  const { start } = starter;

  /** The builder's Start (or the link's): the draft's selection. */
  const startSelection = (from: ReviewFrom = "build") => {
    origin.current = from;
    return start({
      names: orderNames(draft.selected, model.columns),
      onlyDue: model.index.showDue && draft.onlyDue,
      shuffle: draft.shuffle,
      perConcept: draft.perConcept,
      title: deckTitle(draft),
    });
  };

  /** A deck (or a mix of decks) played from the home. */
  const playFromHome = (plan: StartPlan, deckId: string | null) => {
    origin.current = "home";
    setPlaying(deckId);
    void start(plan).finally(() => setPlaying(null));
  };

  const playDue = () => {
    const deck = shuffled(model.dueCards, random);
    if (deck.length) onReview({ deck, title: "Due today", from: "home" });
  };

  return { ...starter, playing, startSelection, playFromHome, playDue };
}

/**
 * `start=1`: once the first card load has answered (and the course list, which
 * scopes generation to the course's documents, is in), go straight to the
 * review of what the hub asked for. Once only: the marker leaves the URL
 * either way. What it starts is rebuilt every render, so the effect reaches
 * the current one by ref.
 */
function useStartOnArrival(input: {
  requested: boolean;
  ready: boolean;
  /** Nothing may be started (pageModel's `startBlocked`). */
  blocked: boolean;
  start: () => Promise<boolean>;
  /** The arrival is over: in the review, or on the home with the reason
   *  nothing started. */
  onSettled: () => void;
}) {
  const live = React.useRef(input);
  React.useEffect(() => { live.current = input; });
  const requested = React.useRef(input.requested);
  const { ready } = input;
  React.useEffect(() => {
    if (!requested.current || !ready) return;
    requested.current = false;
    consumeStartParam();
    const { blocked, start, onSettled } = live.current;
    if (blocked) { onSettled(); return; }
    start()
      .catch(err => console.error("flashcards start failed", err))
      .finally(onSettled);
  }, [ready]);
}

// ── the page ─────────────────────────────────────────────────────────────────

export interface PageInput extends TermCourses {
  /** Test seam: a fixed "now" for due dates and exam countdowns. */
  now?: Date;
  /** Test seam: the shuffle's random source. */
  random: () => number;
}

export function useFlashcardsPage(input: PageInput) {
  const { courses, coursesReady, coursesFailed, reloadCourses, semester, semesterReady, random } = input;
  const { userId } = useUser();
  const arrival = useArrival();
  const { course, courseId, pick } = useCourse(courses, coursesReady, arrival.courseId);
  const courseName = course?.course_name;
  const data = usePageData({ userId, courseId, courseName, semester, semesterReady, now: input.now, concepts: arrival.concepts });
  const { cards, map, sets, draft, dispatch } = data;

  const [build, setBuild] = React.useState<OpenBuild | null>(() => (opensBuilder(arrival) ? { note: "" } : null));
  /** Arrived with `start=1`: nothing is shown as the home until it resolves. */
  const [arriving, setArriving] = React.useState(arrival.start);
  const { review, setReview, markReviewed, leaveReview, removeFromDeck } = useOpenReview(cards.reload);
  const starts = useStarts({ userId, courseId, courseName, semester, random, data, onReview: setReview });
  const { cancel, clearNotice, startSelection } = starts;

  // A different course is a different map: the selection, a run in flight, an
  // open builder and an open review all belong to the one that was left.
  useOnCourseSwitch(courseId, () => {
    cancel();
    dispatch({ type: "reset" });
    setBuild(null);
    setReview(null);
    setArriving(false);
  });

  // "Why nothing started" is about the selection it was said of.
  React.useEffect(() => { clearNotice(); }, [draft, clearNotice]);

  const gates = pageGates(arrival, {
    cardsLoaded: cards.loaded,
    cardsLoading: cards.loading,
    cardsFailed: cards.failed,
    coursesReady,
    coursesFailed,
    mapReady: map.ready,
    setsSettled: sets.settled,
  });
  useStartOnArrival({
    requested: arrival.start,
    ready: gates.start,
    blocked: startBlocked(arrival, courseId, cards.failed),
    start: () => startSelection("link"),
    onSettled: () => setArriving(false),
  });

  const openBuild = (note = "") => {
    clearNotice();
    setBuild({ note });
  };
  /** Back to the home. A selection that was not saved is let go. */
  const closeBuild = () => {
    cancel();
    dispatch({ type: "reset" });
    setBuild(null);
  };

  // A review survives a reload: it is kept while open and read back here.
  const session = useReviewSession({
    userId, courseId, requested: gates.wantsReview, ready: gates.restoreReview, cards: cards.cards, review,
    // Started in the builder, and the builder is coming back too: Back
    // returns to it, as before the reload.
    onRestore: (deck, title) => setReview({ deck, title, from: arrival.build ? "build" : "home" }),
    onLeave: leaveReview,
  });
  useBuildSession({
    userId, courseId, requested: gates.wantsBuild, build, draft, dispatch,
    onRestore: note => setBuild({ note }),
    onLeave: closeBuild,
  });

  const view = pageView({ review, failed: gates.failed, arriving: arriving || session.pending, ready: gates.home, build });

  return {
    ...data,
    ...starts,
    courseId,
    courseLabel: courseLabel(course),
    accent: courseAccent(course),
    pick,
    view,
    place: headerPlace(view, draft),
    importTopic: importTopic(draft),
    session,
    markReviewed,
    removeFromDeck,
    leaveReview,
    openBuild,
    closeBuild,
    /** The header's way back: out of the review, else out of the builder. */
    back: review ? leaveReview : closeBuild,
    reloadCards: () => { void cards.reload(); },
    /** "Try again" on the page that could not load. */
    retry: () => {
      if (coursesFailed) reloadCourses();
      if (cards.failed) void cards.reload();
    },
  };
}

export type FlashcardsPageState = ReturnType<typeof useFlashcardsPage>;
