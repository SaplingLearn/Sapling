// Pure view helpers for the Study Guide page (screens/StudyGuide.tsx).
import { extractErrorDetail, humanizeError, isNotFound } from "@/lib/errorMessage";

// A guide load fails two ways that deserve different UI: the guide's target
// isn't there (normal — a deleted exam, a stale "recent guides" entry, or a
// term with no offering of the course, #475 F4; `message` carries the server's
// sentence when it isn't the exam-deleted one), or the generation itself
// broke. Only the second is worth a red toast, and it carries the ids + term
// it was built from so retry replays the load that failed rather than whatever
// the selects hold when the user gets around to clicking — they can have moved
// on (or been reset by a course/term switch) in between, and a failed load
// leaves nothing on screen tying them to it. `semester` is the term the failed
// load resolved with ("" = unscoped).
// (Until #476 the sharper reason was that a recent-open cleared the exam
// selection outright; that's fixed — the selects now track the open.)
export type GuideProblem =
  | { kind: "missing"; message?: string }
  | { kind: "failed"; message: string; courseId: string; examId: string; semester: string };

/** What a failed guide load is, from its error and the load it was. */
export function guideLoadProblem(
  err: unknown,
  load: { courseId: string; examId: string; semester: string },
): GuideProblem {
  if (!isNotFound(err)) {
    return { kind: "failed", message: humanizeError(err, "Couldn't build that study guide."), ...load };
  }
  // #475 F4: not every 404 means "exam deleted" — strict semester resolution
  // 404s when the course has no offering in the requested term. Surface the
  // server's sentence unless it IS the exam-deleted one (or is absent).
  const { detail } = extractErrorDetail(err);
  return !detail || detail.startsWith("Exam not found") ? { kind: "missing" } : { kind: "missing", message: detail };
}

/** The term one guide load resolves under: its own override when it has one
 *  ("" = explicitly unscoped), else the active selector's. undefined = unscoped. */
export function loadTerm(override: string | undefined, semester: string): string | undefined {
  return (override ?? semester) || undefined;
}

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

// Where an exam is added. The Calendar page is the usual place; a student it
// is hidden from (`hide_calendar`) is pointed at the Study hub instead, whose
// exam tabs end in "Add Exam or Deadline" (components/study/ExamTabs.tsx).

/** The "no exams for this course yet" card's body. */
export function noExamsBody(calendarHidden: boolean): string {
  const where = calendarHidden
    ? "Add one with “Add Exam or Deadline” on the Study page"
    : "Import a syllabus on the Calendar page, or add an assignment with type = Exam,";
  return `Study guides are built one exam at a time. ${where} and it'll show up here.`;
}

/** The "that exam isn't around anymore" card's body. */
export function examGoneBody(calendarHidden: boolean): string {
  const where = calendarHidden
    ? "add one with “Add Exam or Deadline” on the Study page"
    : "add one on the Calendar page";
  return `It was probably deleted. Pick another exam above, or ${where} to build a guide for it.`;
}
