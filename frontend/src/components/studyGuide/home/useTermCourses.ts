"use client";
import React from "react";

import { getCourses, type EnrolledCourse } from "@/lib/api";
import { courseInTerm, useActiveSemester } from "@/lib/useActiveSemester";

export interface TermCourses {
  /** The student's courses in the active term ("" = every term). */
  courses: EnrolledCourse[];
  /** Every course the student is enrolled in, whatever the term. */
  enrolled: EnrolledCourse[];
  /** The active term's label, "" when no term is picked. */
  semester: string;
  /** The course list has answered: an empty one now means "no courses". */
  ready: boolean;
  /** The course list could not be read, so an empty one says nothing. */
  failed: boolean;
  /** Reads the course list again. */
  reload: () => void;
}

/**
 * The courses a new guide can be made for: the active term's, as on the hub.
 * `enrolled` is the whole list, for a card whose guide is from another term.
 */
export function useTermCourses(userId: string): TermCourses {
  const [courses, setCourses] = React.useState<EnrolledCourse[]>([]);
  const [status, setStatus] = React.useState<"loading" | "ready" | "failed">("loading");
  const [attempt, setAttempt] = React.useState(0);
  const [semester] = useActiveSemester();

  React.useEffect(() => {
    if (!userId) return;
    let live = true;
    getCourses(userId)
      .then(r => {
        if (!live) return;
        setCourses(r.courses || []);
        setStatus("ready");
      })
      .catch(err => {
        console.error("study guide courses load failed", err);
        if (live) setStatus("failed");
      });
    return () => { live = false; };
  }, [userId, attempt]);

  const reload = React.useCallback(() => {
    setStatus("loading");
    setAttempt(n => n + 1);
  }, []);
  const scoped = React.useMemo(
    () => (semester ? courses.filter(course => courseInTerm(course, semester)) : courses),
    [courses, semester],
  );
  return { courses: scoped, enrolled: courses, semester, ready: status === "ready", failed: status === "failed", reload };
}
