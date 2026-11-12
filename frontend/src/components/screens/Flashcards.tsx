"use client";
/**
 * Flashcards: say or pick what to study, then review it with ratings and a
 * 3D flip.
 *
 * The page has three states.
 *
 *   HOME (the default): an olive hero that asks what the student wants to
 *   study (describe a set, and it is sorted into one), and the course's sets
 *   as a grid of decks to play, tick together or open.
 *
 *   BUILD: the course's concept map (the Study hub's roadmap columns) and a
 *   tray with the options a review starts with. A step entered on purpose:
 *   from "Sort it", a deck, "Merge into one" or "Build one by hand". Saving
 *   returns to the home; so does "All sets", letting an unsaved selection go.
 *
 *   REVIEW: the flip card for whatever was chosen (components/flashcards/
 *   review). Its way back goes to where it was started from: the home, or the
 *   builder with the selection as it was.
 *
 * The first two live in components/flashcards/home; their rules are pure
 * functions in home/flashcardsModel.ts and home/decksModel.ts.
 *
 * Deep links:
 *   /flashcards?course=<id>                       the home, on that course
 *   /flashcards?course=<id>&concepts=A|B&start=1  straight into the review of
 *     those concepts (the Study hub's "Flashcards" / "Make Flashcards"). A
 *     concept with no cards gets them generated on arrival. `start` leaves the
 *     URL once acted on, so a reload or a Back never starts a second time.
 *   /flashcards?course=<id>&concepts=A|B          the builder, on those concepts
 *
 * The page loads the courses itself and scopes them to the active term. It
 * enters with the Study tools' `tool-enter` fade.
 */
import React from "react";
import { useSearchParams } from "next/navigation";

import { BackLink } from "../BackLink";
import { AIDisclaimerChip } from "../chat/AIDisclaimerChip";
import { Icon } from "../Icon";
import { CoursePicker } from "../study/CoursePicker";
import fc from "./Flashcards.module.css";
import { FlashcardsSkeleton } from "../Skeleton";
import { useUser } from "@/context/UserContext";
import { useIsMobile } from "@/lib/useIsMobile";
import { useActiveSemester, courseInTerm } from "@/lib/useActiveSemester";
import { getCourses, getDocuments, type EnrolledCourse } from "@/lib/api";
import { FlashcardImportModal } from "../flashcards/FlashcardImportModal";
import { namesInSets } from "../flashcards/home/decksModel";
import { FlashcardsHome, FlashcardsHomeSkeleton } from "../flashcards/home/FlashcardsHome";
import {
  deckTitle,
  draftReducer,
  emptyDraft,
  homeModel,
  orderNames,
  shuffled,
  type Card,
  type Draft,
} from "../flashcards/home/flashcardsModel";
import { SetBuilder } from "../flashcards/home/SetBuilder";
import {
  useCards,
  useCourseConcepts,
  useCourseExams,
  useFlashcardSets,
} from "../flashcards/home/useFlashcardsData";
import { useStart, type StartPlan, type StartProgress } from "../flashcards/home/useStart";
import { Review } from "../flashcards/review/Review";
import { BUILD_PARAM, useBuildSession } from "../flashcards/home/buildSession";
import { REVIEW_PARAM, useReviewSession } from "../flashcards/review/reviewSession";
import rv from "../flashcards/review/review.module.css";
import { START_PARAM, consumeStartParam, startStillRequested, studyHref } from "@/lib/toolHrefs";

export function Flashcards({
  now,
  random = Math.random,
}: {
  /** Test seam: a fixed "now" for due dates and exam countdowns. */
  now?: Date;
  /** Test seam: the shuffle's random source. */
  random?: () => number;
}) {
  const isMobile = useIsMobile();
  const { userId, userReady } = useUser();
  const [courses, setCourses] = React.useState<EnrolledCourse[]>([]);
  /** The course list has answered: an empty one now means "no courses". */
  const [coursesReady, setCoursesReady] = React.useState(false);
  const [activeSemester, , semesterHydrated] = useActiveSemester();

  React.useEffect(() => {
    if (!userReady || !userId) return;
    getCourses(userId)
      .then(r => setCourses(r.courses || []))
      .catch(err => console.error("flashcards courses load failed", err))
      .finally(() => setCoursesReady(true));
  }, [userReady, userId]);

  // Same term scoping the old Study host applied before handing the pane its
  // course list.
  const scopedCourses = React.useMemo(
    () => (activeSemester ? courses.filter(c => courseInTerm(c, activeSemester)) : courses),
    [courses, activeSemester],
  );

  return (
    // `tool-enter`: the Study tools' arrival fade (globals.css).
    <div className={`tool-enter ${fc.page}`}>
      <FlashcardsPage
        courses={scopedCourses}
        coursesReady={coursesReady && semesterHydrated}
        isMobile={isMobile}
        semester={activeSemester}
        semesterReady={semesterHydrated}
        now={now}
        random={random}
      />
    </div>
  );
}

// ── the page: which course, which state ─────────────────────────────────────

interface PageProps {
  courses: EnrolledCourse[];
  /** The (term-scoped) course list is final. */
  coursesReady: boolean;
  isMobile: boolean;
  // "" = All semesters (unscoped); fetches gate on
  // semesterReady so a stored term never double-fetches (#141).
  semester: string;
  semesterReady: boolean;
  now?: Date;
  random: () => number;
}

/** What the URL asked for on arrival. */
function useArrival() {
  const searchParams = useSearchParams();
  const [arrival] = React.useState(() => ({
    courseId: searchParams.get("course") || "",
    concepts: (searchParams.get("concepts") || "").split("|").map(x => x.trim()).filter(Boolean),
    // Arrived with `start=1`, and the live URL still says so (see toolHrefs).
    start: searchParams.get(START_PARAM) === "1" && startStillRequested(),
    // A reload inside a review (reviewSession.ts).
    review: searchParams.get(REVIEW_PARAM) === "1",
    // A reload inside the set builder (buildSession.ts).
    build: searchParams.get(BUILD_PARAM) === "1",
  }));
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

function FlashcardsPage({ courses, coursesReady, isMobile, semester, semesterReady, now, random }: PageProps) {
  const { userId } = useUser();
  const arrival = useArrival();
  const { course, courseId, pick } = useCourse(courses, coursesReady, arrival.courseId);
  const courseName = course?.course_name;
  const today = React.useMemo(() => now ?? new Date(), [now]);

  const cards = useCards(userId, semester, semesterReady, now);
  const map = useCourseConcepts(userId, courseId, semester, semesterReady, today);
  const exams = useCourseExams(userId, courseId);
  const sets = useFlashcardSets(userId, courseId);
  const [draft, dispatch] = React.useReducer(draftReducer, arrival.concepts, emptyDraft);
  const inSets = React.useMemo(() => namesInSets(sets.sets), [sets.sets]);
  const model = React.useMemo(
    () => homeModel({ cards: cards.cards, courseId, courseName, concepts: map.concepts, custom: draft.custom, known: inSets, now: cards.now }),
    [cards.cards, cards.now, courseId, courseName, map.concepts, draft.custom, inSets],
  );
  const conceptNames = React.useMemo(() => map.concepts.map(c => c.name), [map.concepts]);

  /** BUILD is open (over the home); `note` is what a sort said on the way in.
   *  A link that names concepts without `start` opens it on them. */
  const [build, setBuild] = React.useState<{ note: string } | null>(
    () => (arrival.concepts.length > 0 && !arrival.start ? { note: "" } : null),
  );
  const [review, setReview] = React.useState<{ deck: Card[]; title: string; from: "home" | "build" | "link" } | null>(null);
  /** Arrived with `start=1`: nothing is shown as the home until it resolves. */
  const [arriving, setArriving] = React.useState(arrival.start);
  /** The deck on the home a review is being started from. */
  const [playing, setPlaying] = React.useState<string | null>(null);
  /** A rating was saved in the review: the home's due counts are stale. */
  const reviewed = React.useRef(false);
  const markReviewed = React.useCallback(() => { reviewed.current = true; }, []);
  /** Where the run in flight was asked from: the URL's `start=1`, the builder's
   *  Start, or a deck on the home. */
  const origin = React.useRef<"home" | "build" | "link">("home");
  const onDeck = React.useCallback(
    (deck: Card[], title: string) => setReview({ deck, title, from: origin.current }),
    [],
  );
  const { start, cancel, clearNotice, progress, running, notice } = useStart({
    userId, courseId, courseName, semester, cards, conceptNames, random, onDeck,
  });

  // A different course is a different map: the selection, a run in flight, an
  // open builder and an open review all belong to the one that was left.
  const lastCourse = React.useRef(courseId);
  React.useEffect(() => {
    const left = lastCourse.current;
    lastCourse.current = courseId;
    if (!left || left === courseId) return;
    cancel();
    dispatch({ type: "reset" });
    setBuild(null);
    setReview(null);
    setArriving(false);
  }, [courseId, cancel]);

  // "Why nothing started" is about the selection it was said of.
  React.useEffect(() => { clearNotice(); }, [draft, clearNotice]);

  const startSelection = (from: "build" | "link" = "build") => {
    origin.current = from;
    return start({
      names: orderNames(draft.selected, model.columns),
      onlyDue: model.index.showDue && draft.onlyDue,
      shuffle: draft.shuffle,
      perConcept: draft.perConcept,
      title: deckTitle(draft),
    });
  };

  // `start=1`: once the first card load has answered (and the course list,
  // which scopes generation to the course's documents, is in), go straight to
  // the review of what the hub asked for. Once only: the marker leaves the URL
  // either way. `startSelection` is rebuilt every render, so the effect
  // reaches the current one by ref.
  const startRef = React.useRef(startSelection);
  React.useEffect(() => { startRef.current = startSelection; });
  const startRequested = React.useRef(arrival.start);
  const cardsAnswered = cards.loaded && !cards.loading;
  const courseKnown = !arrival.courseId || coursesReady;
  React.useEffect(() => {
    if (!startRequested.current || !cardsAnswered || !courseKnown) return;
    startRequested.current = false;
    consumeStartParam();
    // Nothing named, the deck could not be read, or the link's course is not
    // one of the student's (the page fell back to another, whose concepts
    // these are not): the home opens instead, and nothing is generated.
    const elsewhere = !!arrival.courseId && arrival.courseId !== courseId;
    if (!arrival.concepts.length || cards.failed || elsewhere) { setArriving(false); return; }
    // The arrival is over when its run is: in the review, or on the home with
    // the reason nothing started.
    void startRef.current("link").finally(() => setArriving(false));
  }, [cardsAnswered, courseKnown, arrival.concepts.length, arrival.courseId, courseId, cards.failed]);

  /** A deck (or a mix of decks) played from the home. */
  const playFromHome = (plan: StartPlan, deckId: string | null) => {
    origin.current = "home";
    setPlaying(deckId);
    void start(plan).finally(() => setPlaying(null));
  };

  const playDue = () => {
    const deck = shuffled(model.dueCards, random);
    if (deck.length) setReview({ deck, title: "Due today", from: "home" });
  };

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

  // A review started in the builder returns to it (the selection is still
  // there); any other returns to the home.
  const leaveReview = () => {
    setReview(null);
    if (!reviewed.current) return;
    reviewed.current = false;
    void cards.reload();
  };

  // A review survives a reload: it is kept while open and read back here.
  const session = useReviewSession({
    userId, courseId, requested: arrival.review && !arrival.start, ready: cardsAnswered && courseKnown, cards: cards.cards, review,
    // Started in the builder, and the builder is coming back too: Back
    // returns to it, as before the reload.
    onRestore: (deck, title) => setReview({ deck, title, from: arrival.build ? "build" : "home" }),
    onLeave: leaveReview,
  });
  useBuildSession({
    userId, courseId, requested: arrival.build && !arrival.start, build, draft, dispatch,
    onRestore: note => setBuild({ note }),
    onLeave: closeBuild,
  });

  const removeFromDeck = (cardId: string) => {
    setReview(prev => (prev ? { ...prev, deck: prev.deck.filter(c => c.id !== cardId) } : prev));
    void cards.reload();
  };

  const homeReady = coursesReady && cards.loaded && map.ready && sets.settled;
  const courseLabel = course ? course.course_code || course.course_name : "";
  const view = pageView({ review: !!review, arriving: arriving || session.pending, failed: cards.failed, ready: homeReady, build: !!build });

  return (
    <>
      <PageHeader
        isMobile={isMobile}
        courses={courses}
        courseId={courseId}
        onCourse={pick}
        place={headerPlace(view, review, draft)}
        onBack={review ? leaveReview : closeBuild}
        importTopic={draft.selected.length === 1 ? draft.selected[0] : ""}
        onImported={() => { void cards.reload(); }}
      />
      {view === "review" && review && (
        <Review
          deck={review.deck}
          accent={course?.color || "var(--brand-forest)"}
          fromHome={review.from === "home"}
          onRated={markReviewed}
          onDeleted={removeFromDeck}
          onAllSets={leaveReview}
          initial={session.initial}
          onProgress={session.onProgress}
        />
      )}
      {view === "arriving" && <Arriving progress={progress} />}
      {view === "failed" && <LoadFailed onRetry={() => { void cards.reload(); }} />}
      {view === "loading" && <FlashcardsHomeSkeleton />}
      {view === "build" && build && (
        <SetBuilder
          // A course's builder is its own.
          key={courseId}
          courseId={courseId}
          hasConcepts={map.concepts.length > 0}
          model={model}
          exams={exams}
          sets={sets}
          draft={draft}
          dispatch={dispatch}
          progress={progress}
          running={running}
          notice={notice}
          note={build.note}
          onStart={() => { void startSelection(); }}
          onSaved={closeBuild}
        />
      )}
      {view === "home" && (
        <FlashcardsHome
          // A course's home is its own: what was typed or ticked on one is not
          // carried to the next, and a sort in flight for it is dropped.
          key={courseId}
          courseLabel={courseLabel}
          courseId={courseId}
          concepts={map.concepts}
          outline={map.outline}
          model={model}
          exams={exams}
          today={today}
          sets={sets}
          dispatch={dispatch}
          progress={progress}
          running={running}
          notice={notice}
          playing={playing}
          onPlay={playFromHome}
          onPlayDue={playDue}
          onBuild={openBuild}
        />
      )}
    </>
  );
}

type View = "review" | "arriving" | "failed" | "loading" | "build" | "home";

/** Which of the page's states is showing. */
function pageView(is: { review: boolean; arriving: boolean; failed: boolean; ready: boolean; build: boolean }): View {
  if (is.review) return "review";
  if (is.arriving) return "arriving";
  if (is.failed) return "failed";
  if (!is.ready) return "loading";
  return is.build ? "build" : "home";
}

/** What the header shows where the course field is on the home, and the way
 *  back that replaces Import. null: the home (course field, Import). */
interface Place {
  /** What is being reviewed or built. */
  label: string;
  back: string;
  backLabel?: string;
}

function headerPlace(view: View, review: { title: string; from: string } | null, draft: Draft): Place | null {
  if (view === "review" && review) {
    return review.from === "build"
      ? { label: review.title, back: "Back", backLabel: "Back to your selection" }
      : { label: review.title, back: "All sets" };
  }
  if (view === "build") return { label: draft.setId ? draft.givenName || "Edit set" : "New set", back: "All sets" };
  return null;
}

// ── the header ───────────────────────────────────────────────────────────────

/**
 * The hub's header: the title in its line box, the course field beside it,
 * the page's actions on the right. In a review or in the builder the course
 * field gives way to what is being reviewed or built, and Import to the way
 * back.
 */
function PageHeader({
  isMobile, courses, courseId, onCourse, place, onBack, importTopic, onImported,
}: {
  isMobile: boolean;
  courses: EnrolledCourse[];
  courseId: string;
  onCourse: (id: string) => void;
  /** null on the home. */
  place: Place | null;
  onBack: () => void;
  importTopic: string;
  onImported: () => void;
}) {
  const { userId } = useUser();
  const [importOpen, setImportOpen] = React.useState(false);
  const [docs, setDocs] = React.useState<{ id: string; file_name: string; category?: string }[]>([]);

  React.useEffect(() => {
    if (!userId) return;
    getDocuments(userId)
      .then(r => setDocs(r.documents || []))
      .catch(() => setDocs([]));
  }, [userId]);

  return (
    <>
      <header className={fc.head}>
        <h1 className="h-serif" style={{ margin: 0, fontSize: isMobile ? 34 : 42, letterSpacing: "-0.02em", lineHeight: 1.15, color: "var(--text)" }}>Flashcards</h1>
        {place && <span className={fc.deckName} data-testid="flashcards-deck-name">{place.label}</span>}
        {!place && courses.length > 0 && (
          <CoursePicker courses={courses} value={courseId} onChange={onCourse} fullWidth={isMobile} />
        )}
        <div className={fc.actions}>
          <AIDisclaimerChip />
          {!place && (
            <button type="button" className={`btn btn--sm ${fc.action}`} onClick={() => setImportOpen(true)} disabled={!userId}>
              <Icon name="upload" size={13} /> Import
            </button>
          )}
          {/* One way back, last in the row as on every tool page. It goes up
              one level: a review or the builder to the home, the home to the
              hub (on the course this page is showing). */}
          {place
            ? <BackLink label={place.back} ariaLabel={place.backLabel} onClick={onBack} />
            : <BackLink href={studyHref(courseId || null)} label="Study" />}
        </div>
      </header>
      <FlashcardImportModal
        open={importOpen}
        onClose={() => setImportOpen(false)}
        courses={courses}
        defaultCourseId={courseId || courses[0]?.course_id}
        defaultTopic={importTopic}
        documents={docs}
        onImported={onImported}
      />
    </>
  );
}

// ── between the URL and the review ───────────────────────────────────────────

/** Arrived with `start=1`: the deck is loading, or its cards are being made. */
function Arriving({ progress }: { progress: StartProgress | null }) {
  if (!progress) return <div className={rv.stage}><FlashcardsSkeleton /></div>;
  return (
    <div className={rv.stage}>
      <div className={rv.message} role="status">
        <div className="h-serif" style={{ fontSize: "var(--fs-2xl)", color: "var(--text)" }}>Making cards for {progress.name}…</div>
        <div style={{ marginTop: 6 }}>
          {progress.of > 1 ? `${progress.at} of ${progress.of}. ` : ""}From your course material. Review starts as soon as they&apos;re ready.
        </div>
      </div>
    </div>
  );
}

/** The card list could not be read. Offering the map now would call every
 *  concept "no cards yet" and generate over a deck that is really there. */
function LoadFailed({ onRetry }: { onRetry: () => void }) {
  return (
    <div className={rv.stage}>
      <div className={rv.message} role="alert">
        <div className="h-serif" style={{ fontSize: "var(--fs-2xl)", color: "var(--text)" }}>Couldn&apos;t load your flashcards</div>
        <div style={{ marginTop: 6 }}>Check your connection and try again.</div>
        <button type="button" className="btn btn--primary" style={{ marginTop: 16 }} onClick={onRetry}>Try again</button>
      </div>
    </div>
  );
}
