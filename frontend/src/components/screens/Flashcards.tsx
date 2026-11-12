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
 * functions in home/flashcardsModel.ts and home/decksModel.ts. This file is
 * the page's frame only: its state (which course, what is loaded, which state
 * is open) is home/useFlashcardsPage.ts, over the rules in home/pageModel.ts.
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

import { BackLink } from "../BackLink";
import { AIDisclaimerChip } from "../chat/AIDisclaimerChip";
import { Icon } from "../Icon";
import { CoursePicker } from "../study/CoursePicker";
import fc from "./Flashcards.module.css";
import { FlashcardsSkeleton } from "../Skeleton";
import { useUser } from "@/context/UserContext";
import { useIsMobile } from "@/lib/useIsMobile";
import { useLatestRequest } from "@/lib/useLatestRequest";
import { getDocuments, type EnrolledCourse } from "@/lib/api";
import { FlashcardImportModal } from "../flashcards/FlashcardImportModal";
import { FlashcardsHome, FlashcardsHomeSkeleton } from "../flashcards/home/FlashcardsHome";
import type { Place } from "../flashcards/home/pageModel";
import { SetBuilder } from "../flashcards/home/SetBuilder";
import { useFlashcardsPage, useTermCourses, type FlashcardsPageState } from "../flashcards/home/useFlashcardsPage";
import type { StartProgress } from "../flashcards/home/useStart";
import { Review } from "../flashcards/review/Review";
import rv from "../flashcards/review/review.module.css";
import { studyHref } from "@/lib/toolHrefs";

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
  const term = useTermCourses();
  const page = useFlashcardsPage({ ...term, now, random });

  return (
    // `tool-enter`: the Study tools' arrival fade (globals.css).
    <div className={`tool-enter ${fc.page}`}>
      <PageHeader
        isMobile={isMobile}
        courses={term.courses}
        courseId={page.courseId}
        onCourse={page.pick}
        place={page.place}
        onBack={page.back}
        importTopic={page.importTopic}
        onImported={page.reloadCards}
      />
      <PageBody page={page} />
    </div>
  );
}

// ── the page: whichever of its states is showing ────────────────────────────

function PageBody({ page }: { page: FlashcardsPageState }) {
  const { view, courseId, model, exams, sets, draft, dispatch, progress, running, notice } = page;
  switch (view.kind) {
    case "review":
      return (
        <Review
          deck={view.review.deck}
          accent={page.accent}
          fromHome={view.review.from === "home"}
          onRated={page.markReviewed}
          onDeleted={page.removeFromDeck}
          onAllSets={page.leaveReview}
          initial={page.session.initial}
          onProgress={page.session.onProgress}
        />
      );
    case "arriving":
      return <Arriving progress={progress} />;
    case "failed":
      return <LoadFailed onRetry={page.retry} />;
    case "loading":
      return <FlashcardsHomeSkeleton />;
    case "build":
      return (
        <SetBuilder
          // A course's builder is its own.
          key={courseId}
          courseId={courseId}
          hasConcepts={page.map.concepts.length > 0}
          model={model}
          exams={exams}
          sets={sets}
          draft={draft}
          dispatch={dispatch}
          progress={progress}
          running={running}
          notice={notice}
          note={view.build.note}
          onStart={() => { void page.startSelection(); }}
          onSaved={page.closeBuild}
        />
      );
    case "home":
      return (
        <FlashcardsHome
          // A course's home is its own: what was typed or ticked on one is not
          // carried to the next, and a sort in flight for it is dropped.
          key={courseId}
          courseLabel={page.courseLabel}
          courseId={courseId}
          concepts={page.map.concepts}
          outline={page.map.outline}
          model={model}
          exams={exams}
          today={page.today}
          sets={sets}
          dispatch={dispatch}
          progress={progress}
          running={running}
          notice={notice}
          playing={page.playing}
          onPlay={page.playFromHome}
          onPlayDue={page.playDue}
          onBuild={page.openBuild}
        />
      );
  }
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
  const library = useLibraryDocuments(userId, importOpen);

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
        documents={library.documents}
        documentsLoading={library.loading}
        onImported={onImported}
      />
    </>
  );
}

type LibraryDocument = { id: string; file_name: string; category?: string };

/**
 * The student's library documents, for the Import dialog's "From library".
 * Read when the dialog is first opened, not with the page: the list carries
 * every document's summary and notes, and most visits never import. One read
 * per student; a failed one is tried again the next time the dialog opens.
 */
function useLibraryDocuments(userId: string, wanted: boolean) {
  const [loaded, setLoaded] = React.useState<{ userId: string; documents: LibraryDocument[] } | null>(null);
  /** The student a read is in flight (or done) for. */
  const asked = React.useRef("");
  const req = useLatestRequest();

  React.useEffect(() => {
    if (!wanted || !userId || asked.current === userId) return;
    asked.current = userId;
    // Not cancelled when the dialog closes: the answer is kept for the next open.
    const run = req.begin();
    getDocuments(userId)
      .then(r => { if (run.isCurrent()) setLoaded({ userId, documents: r.documents || [] }); })
      .catch(() => {
        if (!run.isCurrent()) return;
        asked.current = "";
        setLoaded({ userId, documents: [] });
      });
  }, [wanted, userId, req]);

  const mine = loaded?.userId === userId ? loaded : null;
  return { documents: mine?.documents ?? NO_DOCUMENTS, loading: mine === null };
}

const NO_DOCUMENTS: LibraryDocument[] = [];

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
