"use client";
// Review in Study, rebuilt (Tutor redesign phase 4, behind `review_v2`;
// design: learn/__fixtures__/review.design.html, the Claude Design board).
// The queue's head: the title "Review", which course the queue serves (one
// chip per course and "All courses", the only chips on the page because they
// are the only thing to pick), and where the student is ("3 of 9"). The old
// head's "N min left" chip is gone: it changed no decision on the page.
import React, { useId } from "react";
import type { EnrolledCourse } from "@/lib/api";
import styles from "./ReviewHead.module.css";

export const REVIEW_COPY = {
  title: "Review",
  allCourses: "All courses",
  scope: "Course",
} as const;

/** The review queue's course scope: "" serves every course. */
export type ReviewScope = { courses: readonly EnrolledCourse[]; value: string; onChange: (courseId: string) => void };

/** "3 of 9": the item on screen among those answered this visit plus what
 *  today's remaining budget still covers (the served item included); null
 *  with nothing on screen. */
export function reviewProgress(done: number, inBudget: number | null | undefined, onScreen: boolean): string | null {
  if (!onScreen || inBudget == null || inBudget < 1) return null;
  return `${done + 1} of ${done + inBudget}`;
}

export function ReviewHead({ scope, progress }: { scope: ReviewScope; progress: string | null }) {
  const name = useId();
  const label = (c: EnrolledCourse) => c.course_code || c.nickname || c.course_name;
  return (
    <div className={styles.head}>
      <h2 className={`h-serif ${styles.title}`}>{REVIEW_COPY.title}</h2>
      {scope.courses.length > 1 && (
        <div role="radiogroup" aria-label={REVIEW_COPY.scope} className={styles.chips} data-testid="review-scope">
          {[...scope.courses.map((c) => ({ id: c.course_id, text: label(c) })), { id: "", text: REVIEW_COPY.allCourses }].map((o) => (
            <label key={o.id || "all"} className={styles.chip} data-picked={o.id === scope.value ? "true" : "false"}
              data-testid={`review-scope-${o.id || "all"}`}>
              <input type="radio" name={name} value={o.id} checked={o.id === scope.value} onChange={() => scope.onChange(o.id)} />
              {o.text}
            </label>
          ))}
        </div>
      )}
      {progress && <span className={styles.progress} data-testid="review-progress">{progress}</span>}
    </div>
  );
}
