"use client";

/**
 * What the quiz did to the learner model, and where to go next (learning-loop
 * spec §13 A147, flag `quiz_results_routing`).
 *
 * Rendered only when the submit reply carries a `learning` block. Three parts,
 * in plain words:
 *   - each skill meter that moved — the quizzed concept, and the prerequisites
 *     and dependents its answers reached through the learner model;
 *   - what is due for review, and when this concept is next due;
 *   - the next step the server chose: review what is due (Study's review
 *     queue), or practise the weakest concept the student is ready for in
 *     Learn (a deep link that opens a session on it).
 *
 * The review queue lives only where the learning loop is on, so a "review"
 * step is offered only when the loop status probe says it is; otherwise the
 * Learn step stands in. Nothing here moves a meter or writes anything.
 */

import React from "react";
import { useLoopStatus } from "@/components/learn/useLoopStatus";
import { useUser } from "@/context/UserContext";
import type { QuizLearning, SkillBand } from "@/lib/quiz/types";

/** The bands as the results say them. */
export const BAND_WORDS: Record<SkillBand, string> = {
  novice: "just starting",
  develop: "developing",
  profic: "proficient",
};

const pct = (value: number) => Math.round(value * 100);

/** Where "Practise X in Learn" goes: Learn opens a session on the concept. */
export function learnHref(learn: NonNullable<QuizLearning["learn"]>): string {
  const params = new URLSearchParams({ topic: learn.concept_name });
  if (learn.course_id) params.set("course", learn.course_id);
  return `/learn?${params.toString()}`;
}

/** Study's flashcards tab hosts the daily review queue. */
export const REVIEW_HREF = "/study?mode=cards";

/** "in 3 days", "tomorrow", "today" — the nearest whole number of days from
 *  now; a time already past is today. */
export function dueIn(iso: string | null, now: Date = new Date()): string | null {
  if (!iso) return null;
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return null;
  const days = Math.max(0, Math.round((at.getTime() - now.getTime()) / 86_400_000));
  if (days === 0) return "today";
  if (days === 1) return "tomorrow";
  return `in ${days} days`;
}

export function changeLine(change: QuizLearning["changes"][number]): string {
  const verb = change.after >= change.before ? "rose" : "fell";
  const band =
    change.band_after === change.band_before
      ? `still ${BAND_WORDS[change.band_after]}`
      : `now ${BAND_WORDS[change.band_after]}`;
  return `${change.concept_name}: ${verb} from ${pct(change.before)}% to ${pct(change.after)}% (${band})`;
}

export function LearningBlock({
  learning,
  conceptName,
}: {
  learning: QuizLearning;
  conceptName: string;
}) {
  const { userId, userReady } = useUser();
  // Probed only when the server suggests the review queue: that is the one
  // step that needs the learning loop on.
  const wantsReview = learning.next_step === "review";
  const { status: loopActive } = useLoopStatus(userId, userReady && wantsReview);
  const reviewOffered = wantsReview && loopActive === true;
  const learn = learning.learn;
  const nextDue = dueIn(learning.review.next_due_at);

  return (
    <section className="quiz-learning" data-testid="quiz-results-learning" aria-label="What changed">
      <h3 className="quiz-learning__title">Your skill meters</h3>
      {learning.changes.length > 0 ? (
        <ul className="quiz-learning__changes">
          {learning.changes.map(change => (
            <li key={change.concept_id} className="quiz-learning__change" data-testid="quiz-results-change">
              {changeLine(change)}
            </li>
          ))}
        </ul>
      ) : (
        <p className="quiz-learning__line" data-testid="quiz-results-no-change">
          No meter moved this time: answers already counted today, or kept out because the question
          could not be checked, don&apos;t change it.
        </p>
      )}

      <p className="quiz-learning__line" data-testid="quiz-results-due">
        {learning.review.due_count > 0
          ? `${learning.review.due_count} ${learning.review.due_count === 1 ? "concept is" : "concepts are"} due for review.`
          : "Nothing is due for review right now."}
        {nextDue ? ` ${conceptName} comes back for review ${nextDue}.` : ""}
      </p>

      {(reviewOffered || learn) && (
        <div className="quiz-learning__next">
          <span className="quiz-learning__next-label">Next:</span>
          {reviewOffered ? (
            <a className="btn btn--primary" href={REVIEW_HREF} data-testid="quiz-next-step-review">
              Review what&apos;s due ({learning.review.due_count})
            </a>
          ) : null}
          {learn && (
            <a
              className={reviewOffered ? "btn" : "btn btn--primary"}
              href={learnHref(learn)}
              data-testid="quiz-next-step-learn"
            >
              Practise {learn.concept_name} in Learn
            </a>
          )}
        </div>
      )}
    </section>
  );
}
