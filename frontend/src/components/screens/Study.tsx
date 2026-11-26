"use client";
/**
 * Study: the one-page-per-course hub (design "Sapling Study v3").
 *
 * The pre-redesign screen that lived here — a TopBar with a Study
 * Guide / Flashcards / Quiz tab strip wrapping two panes — is gone. Its panes
 * are pages of their own now, which is where the hub's tool buttons point:
 *
 *   Study Guide .... /study/guide
 *   Flashcards ..... /flashcards
 *   Quiz ........... /quiz
 *
 * `?mode=guide` / `?mode=cards` were that screen's two panes; they are kept
 * only as redirects so an open tab, a bookmark or a stale link still lands
 * somewhere real instead of on a hub that silently ignores the parameter.
 *
 * The learning loop's reviews (PKG-12; spec §11.3) sit under the hub's header
 * (its `reviews` slot) while the loop is on for the student: the "Due today"
 * queue and the retention check.
 * `?retention-course=<id>` (lib/RetentionDueContext's deep link, and the Study
 * nav item's retention-due dot) opens the retention check on that course, so a
 * retired `?mode=cards` link that carries one lands here, not on Flashcards.
 */
import React from "react";
import { motion } from "framer-motion";
import { useRouter, useSearchParams } from "next/navigation";
import { useUser } from "@/context/UserContext";
import { useIsMobile } from "@/lib/useIsMobile";
import { useActiveSemester, courseInTerm } from "@/lib/useActiveSemester";
import { getCourses, type EnrolledCourse } from "@/lib/api";
import { StudyHub } from "../study/StudyHub";
import { studyGuideHref } from "@/lib/toolHrefs";
import { ReviewSlot } from "../learn/review/ReviewSlot";
import { RailReviews } from "../learn/review/RailReviews";
import { useFlag } from "@/context/FlagsContext";
import { RetentionCheck } from "../learn/RetentionCheck";
import { useLoopStatus } from "../learn/useLoopStatus";
import { useMotionPresets } from "@/lib/motion";
import s from "./Study.module.css";

/** The retention check's deep-link parameter (RetentionDueContext). */
const RETENTION_PARAM = "retention-course";

/** Where a retired `?mode=` lands. Flashcards keeps the course; the Study
 *  Guides home lists every class, so it takes none. A cards link that names a
 *  retention course is the learning loop's "open the retention check": that
 *  check lives on this hub, so it stays here without the retired `mode`. */
function retiredModeHref(mode: string, course: string | null, retentionCourse: string | null): string | null {
  if (mode === "guide") return studyGuideHref();
  if (mode === "cards" && retentionCourse) {
    return `/study?${new URLSearchParams({ [RETENTION_PARAM]: retentionCourse })}`;
  }
  if (mode === "cards") {
    const p = new URLSearchParams();
    if (course) p.set("course", course);
    return p.size ? `/flashcards?${p.toString()}` : "/flashcards";
  }
  return null;
}

/** `scoped`, plus the deep-linked course from `all` when the scope left it out. */
function withLinkedCourse(scoped: EnrolledCourse[], all: EnrolledCourse[], linked: string | null): EnrolledCourse[] {
  if (!linked || scoped.some(c => c.course_id === linked)) return scoped;
  const course = all.find(c => c.course_id === linked);
  return course ? [...scoped, course] : scoped;
}

export function Study() {
  const isMobile = useIsMobile();
  const router = useRouter();
  const { userId, userReady } = useUser();
  const searchParams = useSearchParams();
  const [courses, setCourses] = React.useState<EnrolledCourse[]>([]);
  const [coursesReady, setCoursesReady] = React.useState(false);
  const [activeSemester, , semesterHydrated] = useActiveSemester();

  const reviewV2 = useFlag("review_v2") === "on";
  const mode = searchParams.get("mode");
  const retentionCourse = searchParams.get(RETENTION_PARAM);
  const redirectTo = mode ? retiredModeHref(mode, searchParams.get("course"), retentionCourse) : null;

  React.useEffect(() => {
    // `replace`, not `push`: the retired URL must not sit in history, or Back
    // from the tool bounces through it straight forward again.
    if (redirectTo) router.replace(redirectTo);
  }, [redirectTo, router]);

  React.useEffect(() => {
    if (!userReady || !userId) return;
    getCourses(userId)
      .then(r => setCourses(r.courses || []))
      .catch(err => console.error("study courses load failed", err))
      // A failed load is not a loading one: let the hub show its empty state
      // rather than a skeleton that never resolves.
      .finally(() => setCoursesReady(true));
  }, [userReady, userId]);

  // Scope the hub's course picker to the active semester's courses. Study has
  // no graph fetch of its own, so this client-side filter is all it needs.
  const scopedCourses = React.useMemo(
    () => (activeSemester ? courses.filter(c => courseInTerm(c, activeSemester)) : courses),
    [courses, activeSemester],
  );
  // The retention check offers the same courses, plus the one a deep link names
  // when it is the student's but outside the active semester: the link is
  // about that course, so the check must not quietly switch to another.
  const retentionCourses = React.useMemo(
    () => withLinkedCourse(scopedCourses, courses, retentionCourse),
    [scopedCourses, courses, retentionCourse],
  );

  // Render nothing for the one frame a retired `?mode=` is being replaced:
  // flashing the hub first reads as the navigation having failed.
  if (redirectTo) return null;

  return (
    <StudyHub
      courses={scopedCourses}
      coursesReady={coursesReady}
      semester={activeSemester}
      semesterReady={semesterHydrated}
      initialCourseId={searchParams.get("course")}
      isMobile={isMobile}
      // review_v2 (Tutor redesign): the reviews join the rail under Quick
      // Reviews and open in a modal; off, they sit under the header as before.
      reviews={reviewV2 ? undefined : <LoopReviews courses={retentionCourses} retentionCourse={retentionCourse ?? ""} />}
      railReviews={reviewV2 ? <RailReviews courses={retentionCourses} retentionCourse={retentionCourse ?? ""} /> : undefined}
    />
  );
}

/**
 * The learning loop's reviews under the hub's header: the due queue (every
 * course) and the retention check while the loop is on for the student, side
 * by side inside the hub's own padding (StudyHub's `reviews` slot spans both
 * columns, so the two cards share the hub's edges). A failed status read is not an
 * inactive learning loop: the hub stays, with a retry so the student can
 * still reach due reviews.
 */
function LoopReviews({ courses, retentionCourse }: { courses: EnrolledCourse[]; retentionCourse: string }) {
  const { userId, userReady } = useUser();
  const { status: loopActive, retry: retryLoopStatus } = useLoopStatus(userId, userReady);
  // The reviews arrive after the loop-status read, never with the page: a
  // change worth marking, so they rise into the slot.
  const m = useMotionPresets();
  if (loopActive === "error") {
    return (
      <div className={s.shell}>
        <motion.div role="status" className={`${s.reviews} ${s.statusNotice}`} variants={m.list.item} initial="hidden" animate="shown">
          <p>Couldn&apos;t load due reviews. The rest of Study is still available.</p>
          <button type="button" className="btn btn--sm" onClick={retryLoopStatus} data-testid="review-status-retry">
            Retry due reviews
          </button>
        </motion.div>
      </div>
    );
  }
  if (loopActive !== true) return null;
  return (
    <div className={s.shell}>
      <motion.div className={s.reviews} data-testid="study-reviews" variants={m.list.item} initial="hidden" animate="shown">
        <ReviewSlot userId={userId} courses={courses} />
        <RetentionCheck key={userId} userId={userId} courses={courses} initialCourseId={retentionCourse} />
      </motion.div>
    </div>
  );
}
