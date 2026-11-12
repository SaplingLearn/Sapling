"use client";
import React from "react";

import { getCourses, type EnrolledCourse } from "@/lib/api";
import { courseInTerm, useActiveSemester } from "@/lib/useActiveSemester";

export interface TermCourses {
  /** The student's courses in the active term ("" = every term). */
  courses: EnrolledCourse[];
  /** The active term's label, "" when no term is picked. */
  semester: string;
  /** The course list has answered: an empty one now means "no courses". */
  ready: boolean;
}

/** The courses a new guide can be made for: the active term's, as on the hub. */
export function useTermCourses(userId: string): TermCourses {
  const [courses, setCourses] = React.useState<EnrolledCourse[]>([]);
  const [ready, setReady] = React.useState(false);
  const [semester] = useActiveSemester();

  React.useEffect(() => {
    if (!userId) return;
    let live = true;
    getCourses(userId)
      .then(r => { if (live) setCourses(r.courses || []); })
      .catch(err => console.error("study guide courses load failed", err))
      .finally(() => { if (live) setReady(true); });
    return () => { live = false; };
  }, [userId]);

  const scoped = React.useMemo(
    () => (semester ? courses.filter(course => courseInTerm(course, semester)) : courses),
    [courses, semester],
  );
  return { courses: scoped, semester, ready };
}
