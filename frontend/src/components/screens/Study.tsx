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
 * The learning loop's reviews (PKG-12; spec §11.3) sit above the hub while the
 * loop is on for the student: the "Due today" queue and the retention check.
 * `?retention-course=<id>` (lib/RetentionDueContext's deep link, and the Study
 * nav item's retention-due dot) opens the retention check on that course, so a
 * retired `?mode=cards` link that carries one lands here, not on Flashcards.
 */
import React from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useUser } from "@/context/UserContext";
import { useIsMobile } from "@/lib/useIsMobile";
import { useActiveSemester, courseInTerm } from "@/lib/useActiveSemester";
import { getCourses, type EnrolledCourse } from "@/lib/api";
import { StudyHub } from "../study/StudyHub";
import { studyGuideHref } from "@/lib/toolHrefs";
import { DueQueue } from "../learn/DueQueue";
import { RetentionCheck } from "../learn/RetentionCheck";
import { useLoopStatus } from "../learn/useLoopStatus";

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

export function Study() {
  const isMobile = useIsMobile();
  const router = useRouter();
  const { userId, userReady } = useUser();
  const searchParams = useSearchParams();
  const [courses, setCourses] = React.useState<EnrolledCourse[]>([]);
  const [coursesReady, setCoursesReady] = React.useState(false);
  const [activeSemester, , semesterHydrated] = useActiveSemester();

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

  // Render nothing for the one frame a retired `?mode=` is being replaced:
  // flashing the hub first reads as the navigation having failed.
  if (redirectTo) return null;

  return (
    <>
      <LoopReviews courses={scopedCourses} retentionCourse={retentionCourse ?? ""} />
      <StudyHub
        courses={scopedCourses}
        coursesReady={coursesReady}
        semester={activeSemester}
        semesterReady={semesterHydrated}
        initialCourseId={searchParams.get("course")}
        isMobile={isMobile}
      />
    </>
  );
}

/**
 * The learning loop's reviews above the hub: the due queue (every course) and
 * the retention check while the loop is on for the student. A failed status
 * read is not an inactive learning loop: the hub stays, with a retry so the
 * student can still reach due reviews.
 */
function LoopReviews({ courses, retentionCourse }: { courses: EnrolledCourse[]; retentionCourse: string }) {
  const { userId, userReady } = useUser();
  const { status: loopActive, retry: retryLoopStatus } = useLoopStatus(userId, userReady);
  if (loopActive === "error") {
    return (
      <div role="status" style={{ margin: "14px 32px 0", fontSize: 13 }}>
        <p>Couldn&apos;t load due reviews. The rest of Study is still available.</p>
        <button type="button" className="btn btn--sm" onClick={retryLoopStatus} data-testid="review-status-retry">
          Retry due reviews
        </button>
      </div>
    );
  }
  if (loopActive !== true) return null;
  return (
    <>
      <DueQueue userId={userId} />
      <RetentionCheck key={userId} userId={userId} courses={courses} initialCourseId={retentionCourse} />
    </>
  );
}
