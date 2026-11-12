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
 */
import React from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useUser } from "@/context/UserContext";
import { useIsMobile } from "@/lib/useIsMobile";
import { useActiveSemester, courseInTerm } from "@/lib/useActiveSemester";
import { getCourses, type EnrolledCourse } from "@/lib/api";
import { StudyHub } from "../study/StudyHub";
import { studyGuideHref } from "@/lib/toolHrefs";

/** Where a retired `?mode=` lands, carrying the course along when it has one. */
function retiredModeHref(mode: string, course: string | null): string | null {
  if (mode === "guide") return studyGuideHref(course);
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
  const redirectTo = mode ? retiredModeHref(mode, searchParams.get("course")) : null;

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
    <StudyHub
      courses={scopedCourses}
      coursesReady={coursesReady}
      semester={activeSemester}
      semesterReady={semesterHydrated}
      initialCourseId={searchParams.get("course")}
      isMobile={isMobile}
    />
  );
}
