// Enrolled courses as CustomSelect options, shared by the flashcard import
// modal and the study-guide course picker. Not `lib/quizSelection.ts`'s
// `courseOptions`, which joins code and name into one sorted label.
import type { EnrolledCourse } from "@/lib/api";

/** One option per course, in the given order: labelled by its code with the
 *  catalog name beneath, or by the name alone when there is no code. */
export function courseSelectOptions(courses: EnrolledCourse[]) {
  return courses.map(c => ({
    value: c.course_id,
    label: c.course_code || c.course_name,
    description: c.course_code ? c.course_name : undefined,
  }));
}
