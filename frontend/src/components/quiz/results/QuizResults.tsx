"use client";

/**
 * STUB — Wave 3 (B3) replaces the body. The PROPS are the seam and must not
 * change.
 *
 * The real screen is §5 B3: the growth neighbourhood, the mastery delta line,
 * the score and XP rule, the missed list with its disclosures and per-item
 * "Ask about this", the perfect-run line, and the three exits.
 */

import React from "react";
import type { NeighbourNode } from "@/lib/graph/neighbourhood";
import { queueOf } from "@/lib/quiz/machine";
import type { QuizActions } from "@/lib/quiz/useQuizSession";
import type { QuizSession } from "@/lib/quiz/types";
import { sourceLabel } from "@/lib/quiz/exits";
import type { QuizConceptSummary } from "../question/QuizQuestion";

export interface QuizResultsProps {
  session: QuizSession;
  actions: QuizActions;
  concept: QuizConceptSummary;
  neighbourhood: { siblings: NeighbourNode[] };
  prefersReducedMotion: boolean;
}

export function QuizResults({ session, actions, concept }: QuizResultsProps) {
  const result = session.result;
  const queue = queueOf(session.scope);
  const hasNext = session.queueIndex + 1 < queue.length;
  const missed = result ? result.total - result.score : 0;

  return (
    <div className="quiz-stub" data-testid="quiz-results">
      <h2 className="h-serif">{concept.name}</h2>
      <p data-testid="quiz-results-score">
        {result ? `${result.score} of ${result.total} correct` : ""}
      </p>
      <p data-testid="quiz-results-mastery">
        {result
          ? `${Math.round(result.mastery_before * 100)}% → ${Math.round(result.mastery_after * 100)}%`
          : ""}
      </p>
      {session.xp && (
        <p data-testid="quiz-results-xp">
          +{session.xp.after - session.xp.before} XP · {session.xp.streak}-day streak
        </p>
      )}

      <div className="quiz-stub__actions">
        {hasNext ? (
          <button
            type="button"
            className="btn btn--primary"
            data-testid="quiz-next-concept"
            onClick={() => actions.nextInQueue()}
          >
            Next concept
          </button>
        ) : missed > 0 ? (
          <button
            type="button"
            className="btn btn--primary"
            data-testid="quiz-practise-missed"
            onClick={() => actions.practiseMissed()}
          >
            Practise the {missed === 1 ? "one" : `${missed}`} you missed
          </button>
        ) : (
          <button
            type="button"
            className="btn btn--primary"
            data-testid="quiz-again"
            onClick={() =>
              actions.start({
                intent: session.intent,
                scope: session.scope,
                conceptId: session.conceptId,
                courseId: session.courseId,
              })
            }
          >
            Keep going — quiz again
          </button>
        )}
        <button
          type="button"
          className="btn"
          data-testid="quiz-back-to-source"
          onClick={() => actions.exit()}
        >
          {sourceLabel(session.source.kind)}
        </button>
        <button
          type="button"
          className="btn btn--ghost"
          data-testid="quiz-done"
          onClick={() => actions.exit("/quiz")}
        >
          Done
        </button>
      </div>
    </div>
  );
}
