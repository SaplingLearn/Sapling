/**
 * W3.4 / W8.5: one copy system for Learn ↔ Study ↔ Quiz handoffs.
 *
 * Labels stay stable across wrap-up, Quiz results, Study Hub Focus, retention
 * empty states and LoopNotices. Hrefs reuse `studyHref` / `buildQuizHref` /
 * Learn query params — no second planner. Callers pass hide_* visibility and
 * omit a null / filtered CTA (NavFeatureGate would only bounce to /dashboard).
 *
 * W3.3b/c: "Practice what's due" is the Quiz cue-stream entry (`scope=due` +
 * learner_next due[] queue when known, else course+start) — never a second
 * Learn teach path.
 */

import { buildQuizHref, practiceDueQueue } from "@/lib/quiz/source";
import { studyHref } from "@/lib/toolHrefs";

/** Canonical CTA labels (W8.5 phrasing + "quiz this concept" + Practice). */
export const HANDOFF_COPY = {
  dueOnStudy: "Due on Study",
  dueOnStudyCounted: (n: number) => `Due on Study (${n})`,
  dueOnStudyDot: (n: number) => `Due on Study · ${n}`,
  continueInTutor: "Continue in Tutor",
  continueLearning: (name: string) => `Continue learning: ${name}`,
  quizThisConcept: "Quiz this concept",
  /** W3.3b: Quiz cue stream on due (not Teach / LoopLearn). */
  practiceWhatsDue: "Practice what's due",
  seeOnMap: "See on your map",
  /** Budget pause only — flashcards while the tutor is capped. */
  reviewFlashcards: "Review flashcards",
} as const;

export type HandoffVisibility = {
  study: boolean;
  tutor: boolean;
  quiz: boolean;
  tree: boolean;
};

export type HandoffCta = {
  key: "study" | "tutor" | "quiz" | "tree";
  label: string;
  href: string;
  testId: string;
};

export function handoffStudyHref(courseId?: string | null): string {
  return studyHref(courseId);
}

export function handoffLearnHref(opts: {
  conceptId?: string | null;
  conceptName?: string | null;
  courseId?: string | null;
  /** Defaults to `socratic` (same as `learnHrefForNode`) when any scope is set. */
  mode?: string | null;
} = {}): string {
  const p = new URLSearchParams();
  if (opts.conceptName?.trim()) p.set("topic", opts.conceptName.trim());
  if (opts.conceptId?.trim()) p.set("concept", opts.conceptId.trim());
  const mode = opts.mode === null ? null : (opts.mode?.trim() || "socratic");
  if (mode && (opts.conceptName || opts.conceptId || opts.courseId)) p.set("mode", mode);
  if (opts.courseId?.trim()) p.set("course", opts.courseId.trim());
  const q = p.toString();
  return q ? `/learn?${q}` : "/learn";
}

/** Concept-scoped Quiz with `start=1`; returns to Study (or an override). */
export function handoffQuizConceptHref(
  conceptId: string,
  opts: { courseId?: string | null; returnTo?: string } = {},
): string {
  const returnTo =
    opts.returnTo ?? (opts.courseId ? studyHref(opts.courseId) : "/study");
  return buildQuizHref(
    { concept: conceptId },
    { kind: "link", returnTo },
    { start: true },
  );
}

/** Course Quiz home; `start` arms a course queue when the home supports it. */
export function handoffQuizCourseHref(
  courseId: string,
  opts: { returnTo?: string; start?: boolean } = {},
): string {
  return buildQuizHref(
    { course: courseId },
    { kind: "link", returnTo: opts.returnTo ?? studyHref(courseId) },
    { start: opts.start === true },
  );
}

/**
 * W3.3c Practice entry: `scope=due` + learner_next `due[]` as the session
 * queue (`queueStartRequest`) + `start=1`, else course queue + `start=1`.
 * Same shape as Hub `dueReviewsQuizHref`, with the empty-due fallback wrap-up
 * needs when it has no due ids yet.
 */
export function handoffPracticeDueHref(
  courseId: string,
  dueConceptIds: readonly string[] = [],
): string {
  const queue = practiceDueQueue(dueConceptIds);
  if (queue.length > 0) {
    return buildQuizHref(
      { scope: "due", queue },
      { kind: "link", returnTo: studyHref(courseId) },
      { start: true },
    );
  }
  return handoffQuizCourseHref(courseId, { start: true });
}

export function handoffTreeHref(opts: {
  courseId?: string | null;
  nodeId?: string | null;
} = {}): string {
  const p = new URLSearchParams();
  if (opts.nodeId?.trim()) p.set("node", opts.nodeId.trim());
  else if (opts.courseId?.trim()) p.set("course", opts.courseId.trim());
  const q = p.toString();
  return q ? `/tree?${q}` : "/tree";
}

/**
 * Wrap-up / close CTAs. Study stays the Hub handoff; Practice is the Quiz cue
 * stream (due[] queue or course+start) when Study and Quiz are both visible;
 * "Quiz this concept" only when a measured concept id is known. Retention +
 * "Start a new session" stay beside these in ClosePanel.
 */
export function closeHandoffCtas(input: {
  courseId: string | null;
  quizConceptId?: string | null;
  /** Learner-next due ids when known; empty → course+start Practice href. */
  dueConceptIds?: readonly string[];
  visibility: HandoffVisibility;
}): HandoffCta[] {
  const { courseId, quizConceptId, dueConceptIds, visibility } = input;
  const out: HandoffCta[] = [];
  if (visibility.study) {
    out.push({
      key: "study",
      label: HANDOFF_COPY.dueOnStudy,
      href: handoffStudyHref(courseId),
      testId: "loop-close-study-link",
    });
  }
  // Practice needs a Study return target and a visible Quiz surface.
  if (visibility.study && visibility.quiz && courseId) {
    out.push({
      key: "quiz",
      label: HANDOFF_COPY.practiceWhatsDue,
      href: handoffPracticeDueHref(courseId, dueConceptIds ?? []),
      testId: "loop-close-practice-link",
    });
  }
  if (visibility.quiz && quizConceptId) {
    out.push({
      key: "quiz",
      label: HANDOFF_COPY.quizThisConcept,
      href: handoffQuizConceptHref(quizConceptId, { courseId }),
      testId: "loop-close-quiz-link",
    });
  }
  if (visibility.tree) {
    out.push({
      key: "tree",
      label: HANDOFF_COPY.seeOnMap,
      href: handoffTreeHref({ courseId }),
      testId: "loop-close-tree-link",
    });
  }
  return out;
}

/** Retention empty / finished: Study due + Tutor, hide_* filtered. */
export function retentionEmptyHandoffCtas(input: {
  courseId: string | null;
  visibility: Pick<HandoffVisibility, "study" | "tutor">;
}): HandoffCta[] {
  const out: HandoffCta[] = [];
  if (input.visibility.study) {
    out.push({
      key: "study",
      label: HANDOFF_COPY.dueOnStudy,
      href: handoffStudyHref(input.courseId),
      testId: "retention-study-link",
    });
  }
  if (input.visibility.tutor) {
    out.push({
      key: "tutor",
      label: HANDOFF_COPY.continueInTutor,
      href: handoffLearnHref({ courseId: input.courseId }),
      testId: "retention-tutor-link",
    });
  }
  return out;
}

/**
 * Practice-unavailable notice: Due on Study + Quiz on the first named concept
 * (not full W3.3 practice mode — no due-queue fetch).
 */
export function practiceUnavailableHandoffCtas(input: {
  courseId: string | null;
  conceptIds: readonly string[];
  visibility: Pick<HandoffVisibility, "study" | "quiz">;
}): HandoffCta[] {
  const out: HandoffCta[] = [];
  if (input.visibility.study) {
    out.push({
      key: "study",
      label: HANDOFF_COPY.dueOnStudy,
      href: handoffStudyHref(input.courseId),
      testId: "loop-practice-study-link",
    });
  }
  const conceptId = input.conceptIds.find((id) => id.trim());
  if (input.visibility.quiz && conceptId) {
    out.push({
      key: "quiz",
      label: HANDOFF_COPY.quizThisConcept,
      href: handoffQuizConceptHref(conceptId, { courseId: input.courseId }),
      testId: "loop-practice-quiz-link",
    });
  }
  return out;
}
