import type { EnrolledCourse } from "@/lib/api";

/**
 * The colour a class has everywhere else in the app: the one on the student's
 * enrolment, as the Study hub's class picker and the Library's sidebar draw
 * it. A class with none (or one the student has left) is muted, as it is there.
 */
export const classColor = (courses: EnrolledCourse[], courseId: string): string =>
  courses.find(course => course.course_id === courseId)?.color || "var(--text-muted)";
