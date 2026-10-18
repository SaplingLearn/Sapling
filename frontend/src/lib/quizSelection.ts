// Pure course/concept selection logic, unit-testable without rendering React.
//
// Written for the old quiz picker's two-step flow (choose a course, then a
// concept within it), which it fixed two bugs in: a single flat dropdown built
// straight from graph nodes (a) never surfaced enrolled courses that had no
// concept nodes yet, and (b) listed same-named concepts from different courses
// side by side, reading as duplicates.
//
// That picker is gone. What survives it is `resolveInitialSelection`, now the
// id half of `lib/quiz/proposals.ts::entrySelection` — the resolver behind
// `/quiz?concept=<nodeId>`. Its "unknown id selects nothing" answer is the
// reason the redesign reuses this rather than re-deriving it: a deep link into
// a term the student is not viewing has to read as unresolved, not as a quiz on
// something off-screen. `courseOptions` / `conceptOptionsForCourse` remain
// available for any grouped picker that wants them.

export interface QuizConcept {
  id: string;
  name: string;
  course_id: string | null;
  course_code: string | null;
}

export interface QuizCourseInput {
  course_id: string;
  course_code: string;
  course_name: string;
  nickname?: string | null;
}

export interface SelectOption {
  value: string;
  label: string;
}

/** Human label for a course option: code plus the student's nickname or the
 * catalog name, e.g. "CAS CS 330 — Intro to Algorithms". Falls back to the
 * code alone when no name is available. */
function courseLabel(course: QuizCourseInput): string {
  const name = (course.nickname || course.course_name || "").trim();
  const code = (course.course_code || "").trim();
  if (code && name) return `${code} — ${name}`;
  return code || name || "Course";
}

/** All enrolled courses as dropdown options, sorted by course code so the list
 * is stable regardless of enrollment order. Every enrolled course is offered —
 * the concept step handles courses that have no concepts yet. */
export function courseOptions(courses: QuizCourseInput[]): SelectOption[] {
  return courses
    .map(c => ({ value: c.course_id, label: courseLabel(c) }))
    .sort((a, b) => a.label.localeCompare(b.label));
}

/** Concepts belonging to `courseId`, as dropdown options. The label is the
 * concept name alone — the course is already chosen, so prefixing the code
 * would be redundant. Returns [] when no course is selected. */
export function conceptOptionsForCourse(
  concepts: QuizConcept[],
  courseId: string | null,
): SelectOption[] {
  if (!courseId) return [];
  return concepts
    .filter(c => c.course_id === courseId)
    .map(c => ({ value: c.id, label: c.name }))
    .sort((a, b) => a.label.localeCompare(b.label));
}

/** Resolve the initial (course, concept) pair from a deep-linked concept id
 * (e.g. arriving from a "Quiz me on X" link). When the concept is known we
 * preselect its course too, so the concept dropdown is immediately populated.
 * Unknown/absent ids leave both unset so the student picks a course first. */
export function resolveInitialSelection(
  concepts: QuizConcept[],
  initialConceptId: string | null | undefined,
): { courseId: string | null; conceptId: string | null } {
  if (!initialConceptId) return { courseId: null, conceptId: null };
  const match = concepts.find(c => c.id === initialConceptId);
  if (!match) return { courseId: null, conceptId: null };
  return { courseId: match.course_id, conceptId: match.id };
}
