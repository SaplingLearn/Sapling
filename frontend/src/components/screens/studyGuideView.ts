// Pure view helpers for the Study screen's guide pane (GuideMode).

/** Color of a picker's "01"/"02" step marker: lit once that step has a value,
 *  dimmed when only its prerequisite step is done, muted otherwise. */
export function stepNumberColor(value: string, prerequisite: string): string {
  if (value) return "var(--accent)";
  return prerequisite ? "var(--text-dim)" : "var(--text-muted)";
}

/** The exam picker's placeholder for the current course/loading state. */
export function examPickerPlaceholder(loadingExams: boolean, courseId: string): string {
  if (loadingExams) return "Loading…";
  return courseId ? "Pick an exam…" : "Select a course first";
}

/** Whether a Recent guides entry is the guide currently selected. */
export function isOpenGuide(
  entry: { course_id: string; exam_id: string },
  courseId: string,
  examId: string,
): boolean {
  return entry.course_id === courseId && entry.exam_id === examId;
}
