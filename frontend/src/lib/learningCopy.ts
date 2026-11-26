/**
 * One word per idea across Tutor, Study, Quiz and Tree (Tutor redesign phase 2;
 * the frontend audit's "One product, many vocabularies"). A label that names
 * one of these ideas comes from here, so two screens cannot drift apart.
 *
 * - Start: "New session" wherever one starts; "Continue {title}" resumes one;
 *   "Learn" (or "Learn {concept}" where the concept is not already the
 *   subject) opens the Tutor on a concept from another surface.
 * - Due: an FSRS review and nothing else, and its place is "Review". A
 *   retention check is "ready"; an assignment keeps its own "due".
 * - Check: the check-in, a question, a hint, graded / not graded, wrap up, the
 *   retention check.
 * - Students never read the machinery: `BANNED_STUDENT_TERMS` is pinned by
 *   learningCopy.test.ts and by the Tutor's render test.
 */

/** "1 concept", "3 concepts"; `many` for an irregular plural. */
export function plural(n: number, one: string, many = `${one}s`): string {
  return `${n} ${n === 1 ? one : many}`;
}

export const LEARNING_COPY = {
  /** Starts a session (the Tutor's sidebar, home and wrap-up alike). */
  newSession: "New session",
  starting: "Starting…",
  /** Resumes the open session. */
  continueSession: (title: string) => `Continue ${title}`,
  /** Opens the Tutor on a concept that is already the screen's subject. */
  learn: "Learn",
  /** Opens the Tutor on a concept named nowhere else on the screen. */
  learnConcept: (name: string) => `Learn ${name}`,
  /** Opens the Tutor home (no concept, no session). */
  openTutor: "Open Tutor",
  /** Approves the plan and starts teaching it. */
  startPlan: "Start this plan",
  /** The place FSRS reviews live (Study's review queue and flashcards). */
  review: "Review",
  /** A link to Review that carries its count: "3 reviews due", else "Review". */
  reviewLink: (n?: number | null) => (n && n > 0 ? `${plural(n, "review")} due` : "Review"),
  /** The review count as a line of its own. */
  reviewsDue: (n: number) => (n > 0 ? `${plural(n, "review")} due` : "Nothing due right now"),
  /** The Quiz cue stream on the due concepts (W3.3b). */
  practiceDue: "Practice what's due",
  quizConcept: "Quiz this concept",
  seeOnMap: "See on your map",
} as const;

/**
 * Words that name the learning system's machinery, not what the student knows
 * or does (the audit's banned list). "Mastery" belongs only to the Mastered
 * badge; "evidence", "budget" and "scope" are internal; H0–H6 are the hint
 * ladder's rungs.
 */
export const BANNED_STUDENT_TERMS =
  /\b(probes?|rungs?|H[0-6]|p_known|BKT|FSRS|bounded|independent(ly)?|observations?|evidence|eligible|budget|scope|grader|checks drafting|mastery)\b/i;
