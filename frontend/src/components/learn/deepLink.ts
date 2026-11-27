// The Learn deep links LoopLearn reads (moved out of LoopLearn.tsx unchanged).
import { useEffect, useRef } from "react";
import { readResumeParam } from "./resumeParam";

/** The Learn deep links (Dashboard, Tree, notetaker, quiz): read ONCE at mount,
 *  so a consumed `?resume=` never re-applies on a session or course switch.
 *  `note`: Send to tutor's note, whose title is `topic`. `concept` (#866 K05):
 *  the node id of the concept a "learn this" link is about (`topic` is its name),
 *  or Send to tutor's linked concepts, comma-joined. `milestone` (with
 *  `course`): the calendar's Prepare opens that exam's milestone page. */
export type DeepLink = { resume: string | null; topic: string; course: string; mode: string; suggest: string; note: string; concept: string; milestone: string };
export const readDeepLink = (p: { get(name: string): string | null }): DeepLink => ({
  resume: readResumeParam(p),
  topic: (p.get("topic") ?? "").trim(),
  course: (p.get("course") ?? "").trim(),
  mode: (p.get("mode") ?? "").trim(),
  suggest: (p.get("suggest") ?? "").trim(),
  note: (p.get("note") ?? "").trim(),
  concept: (p.get("concept") ?? "").trim(),
  milestone: (p.get("milestone") ?? "").trim(),
});
export const hasDeepLink = (d: DeepLink) => !!(d.resume || d.topic || d.course || d.mode || d.suggest || d.note || d.concept || d.milestone);

/** `?course=…&milestone=…`: once the student's courses are in and the course is
 *  theirs, open that course's milestone page (the Tutor's `milestones`), once. */
export function useMilestoneLink(d: DeepLink, courses: readonly { course_id: string }[] | null, show: (courseId: string, milestone: string) => void) {
  const done = useRef(false);
  useEffect(() => {
    if (done.current || !d.milestone || !d.course || !courses?.some((c) => c.course_id === d.course)) return;
    done.current = true;
    show(d.course, d.milestone);
  }, [d, courses, show]);
}
