"use client";

/**
 * What the quiz did to the learner model, and where to go next (learning-loop
 * spec §13 A147 / W7.7, flag `quiz_results_routing`).
 *
 * Rendered only when the submit reply carries a `learning` block. Three parts,
 * in plain words:
 *   - each skill meter that moved — the quizzed concept, and the prerequisites
 *     and dependents its answers reached through the learner model;
 *   - what is due for review, and when this concept is next due;
 *   - the next steps on the same learner-model spine as Tree / Study / Tutor:
 *     review what is due (Study), practise the weakest ready concept (Learn),
 *     and see the quizzed concept on the Tree.
 *
 * Hrefs reuse `studyHref`, `learnHrefForNode`, and `treeReturnTo` — no forked
 * ranking. The review queue lives only where the learning loop is on, so a
 * "review" step is offered only when the loop status probe says it is;
 * otherwise the Learn step stands in. A step whose page a hide flag hides
 * (`hide_study`, `hide_tutor`, `hide_tree`) is never offered: NavFeatureGate
 * would only bounce it to /dashboard. Nothing here moves a meter or writes
 * anything.
 */

import { HandoffLink } from "@/components/ui/HandoffLink";
import React from "react";
import { useLoopStatus } from "@/components/learn/useLoopStatus";
import { useStudyNavShown } from "@/components/useRetentionNav";
import { useFlag } from "@/context/FlagsContext";
import { useUser } from "@/context/UserContext";
import { handoffLearnHref, handoffStudyHref, handoffTreeHref } from "@/lib/learningHandoffs";
import { LEARNING_COPY } from "@/lib/learningCopy";
import { BAND_WORDS } from "@/lib/quiz/proposals";
import type { QuizLearning } from "@/lib/quiz/types";

/** The bands as the results say them: the quiz home's words. */
export { BAND_WORDS };

const pct = (value: number) => Math.round(value * 100);

/** Where "Learn {concept}" goes: Learn opens a session on the concept (#866 K05). */
export function learnHref(learn: NonNullable<QuizLearning["learn"]>): string {
  return handoffLearnHref({
    conceptId: learn.concept_id,
    conceptName: learn.concept_name,
    courseId: learn.course_id,
  });
}

/** Study hub for the quizzed course — same builder Study / Dashboard use. */
export function reviewHref(courseId?: string | null): string {
  return handoffStudyHref(courseId);
}

/** Tree opened on the quizzed concept (W3.4 / W8.5 "See on your map"). */
export function conceptTreeHref(conceptId: string): string {
  return handoffTreeHref({ nodeId: conceptId });
}

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

/** "rose from 35% to 62% (now developing)": one skill meter's move. */
export function skillMove(change: QuizLearning["changes"][number]): string {
  const verb = change.after >= change.before ? "rose" : "fell";
  const band =
    change.band_after === change.band_before
      ? `still ${BAND_WORDS[change.band_after]}`
      : `now ${BAND_WORDS[change.band_after]}`;
  return `${verb} from ${pct(change.before)}% to ${pct(change.after)}% (${band})`;
}

export function changeLine(change: QuizLearning["changes"][number]): string {
  return `${change.concept_name}: ${skillMove(change)}`;
}

/** The quizzed concept's own move, which the results lead with. */
export function ownChange(learning: QuizLearning, conceptId: string): QuizLearning["changes"][number] | null {
  return learning.changes.find((c) => c.concept_id === conceptId) ?? null;
}

export function LearningBlock({
  learning,
  conceptName,
  conceptId,
  courseId,
}: {
  learning: QuizLearning;
  conceptName: string;
  /** Quizzed concept id — Tree deep link. */
  conceptId: string;
  /** Quizzed course — Study hub deep link when known. */
  courseId?: string | null;
}) {
  const { userId, userReady } = useUser();
  // Probed only when the server suggests the review queue: that is the one
  // step that needs the learning loop on.
  const wantsReview = learning.next_step === "review";
  const { status: loopActive } = useLoopStatus(userId, userReady && wantsReview);
  const studyShown = useStudyNavShown();
  const tutorShown = useFlag("hide_tutor") !== "on";
  const treeShown = useFlag("hide_tree") !== "on";
  const reviewOffered = wantsReview && loopActive === true && studyShown;
  const learn = tutorShown ? learning.learn : null;
  const treeHref = treeShown && conceptId ? conceptTreeHref(conceptId) : null;
  const nextDue = dueIn(learning.review.next_due_at);
  const hasNext = reviewOffered || Boolean(learn) || Boolean(treeHref);
  const others = learning.changes.filter((c) => c.concept_id !== conceptId);

  return (
    <section className="quiz-learning" data-testid="quiz-results-learning" aria-label="What changed">
      {/* One measure: the quizzed concept's own move leads the results (its
          header line); the meters its evidence also reached sit here. */}
      {others.length > 0 && <h3 className="quiz-learning__title">Also moved</h3>}
      {others.length > 0 ? (
        <ul className="quiz-learning__changes">
          {others.map(change => (
            <li key={change.concept_id} className="quiz-learning__change" data-testid="quiz-results-change">
              {changeLine(change)}
            </li>
          ))}
        </ul>
      ) : learning.changes.length > 0 ? null : (
        <p className="quiz-learning__line" data-testid="quiz-results-no-change">
          No skill meter moved this time. Each question counts toward your meters once a day, and
          only if it passed its checks.
        </p>
      )}

      <p className="quiz-learning__line" data-testid="quiz-results-due">
        {learning.review.due_count > 0
          ? `${learning.review.due_count} ${learning.review.due_count === 1 ? "concept is" : "concepts are"} due for review.`
          : "Nothing is due for review right now."}
        {nextDue ? ` ${conceptName} comes back for review ${nextDue}.` : ""}
      </p>

      {hasNext && (
        <div className="quiz-learning__next" data-testid="quiz-learning-next">
          <span className="quiz-learning__next-label">Next:</span>
          {reviewOffered ? (
            <HandoffLink variant="primary" href={reviewHref(courseId)} testId="quiz-next-step-review">
              {LEARNING_COPY.reviewLink(learning.review.due_count)}
            </HandoffLink>
          ) : null}
          {learn && (
            <HandoffLink variant={reviewOffered ? "secondary" : "primary"} href={learnHref(learn)} testId="quiz-next-step-learn">
              {LEARNING_COPY.learnConcept(learn.concept_name)}
            </HandoffLink>
          )}
          {treeHref && (
            <HandoffLink variant={reviewOffered || learn ? "secondary" : "primary"} href={treeHref} testId="quiz-next-step-tree">
              {LEARNING_COPY.seeOnMap}
            </HandoffLink>
          )}
        </div>
      )}
    </section>
  );
}
