"use client";

/**
 * STUB — Wave 3 (B2) replaces the body. The PROPS are the seam and must not
 * change.
 *
 * Enough of the flow is wired to drive the machine by hand: pick an option,
 * Submit, then Next / See results, and Leave with its confirmation. That is the
 * whole loop the data layer has to survive.
 *
 * The real screen is §5 B2: the progress rail, the concept header, the stem,
 * the `AnswerOption` radiogroup, the feedback line, flag, "Ask about this", the
 * leave dialog, the AskPanel sheet and the keyboard map.
 */

import React from "react";
import type { QuizActions } from "@/lib/quiz/useQuizSession";
import type { QuizConfig, QuizSession } from "@/lib/quiz/types";

export interface QuizConceptSummary {
  id: string;
  name: string;
  courseCode: string;
  color: string;
  tier: string;
  mastery: number;
}

export interface QuizQuestionProps {
  session: QuizSession;
  actions: QuizActions;
  config: QuizConfig | null;
  concept: QuizConceptSummary;
  userId: string;
  courseId: string | null;
}

export function QuizQuestion({ session, actions, concept }: QuizQuestionProps) {
  const item = session.items[session.cursor];
  const total = session.items.length;
  const isLast = session.cursor >= total - 1;
  const revealed = session.phase === "answered";

  if (session.phase === "generating") {
    return (
      <div className="quiz-stub" data-testid="quiz-generating">
        <p className="quiz-stub__phase label-micro">Writing your quiz…</p>
      </div>
    );
  }

  return (
    <div className="quiz-stub" data-testid="quiz-panel">
      <p className="quiz-stub__phase label-micro">
        {concept.name} · question {session.cursor + 1} of {total} · {session.phase}
      </p>
      <h2 className="h-serif">{item?.question.question ?? ""}</h2>

      <div role="radiogroup" aria-label="Answer choices" data-testid="quiz-answer-options">
        {(item?.question.options ?? []).map((option, index) => (
          <button
            type="button"
            key={option.label}
            className="btn"
            role="radio"
            aria-checked={item?.selectedIndex === index}
            data-testid={`quiz-answer-option-${option.label}`}
            disabled={session.phase !== "active"}
            onClick={() => actions.select(index)}
          >
            {option.label}. {option.text}
          </button>
        ))}
      </div>

      <p data-testid="quiz-review-verdict" aria-live="polite">
        {revealed && item?.verdict
          ? `${item.verdict.isCorrect ? "Correct." : "Not quite."} ${item.verdict.explanation}`
          : ""}
      </p>

      <div className="quiz-stub__actions">
        <button
          type="button"
          className="btn"
          data-testid="quiz-leave"
          onClick={() => actions.requestLeave()}
        >
          Leave
        </button>
        <button type="button" className="btn" data-testid="quiz-flag" onClick={() => actions.flag()}>
          This question is confusing
        </button>
        {revealed ? (
          <button
            type="button"
            className="btn btn--primary"
            data-testid="quiz-next"
            onClick={() => actions.next()}
          >
            {isLast ? "See results" : "Next"}
          </button>
        ) : (
          <button
            type="button"
            className="btn btn--primary"
            data-testid="quiz-submit-answer"
            aria-disabled={item?.selectedIndex === null}
            disabled={item?.selectedIndex === null || session.phase !== "active"}
            onClick={() => actions.submitAnswer()}
          >
            {session.phase === "submitting" ? "Scoring…" : "Submit"}
          </button>
        )}
      </div>

      {session.phase === "confirm-leave" && (
        <div className="quiz-stub__actions" data-testid="quiz-leave-dialog">
          <p>Leave this quiz? Your answers so far are saved.</p>
          <button
            type="button"
            className="btn"
            data-testid="quiz-leave-cancel"
            onClick={() => actions.cancelLeave()}
          >
            Keep going
          </button>
          <button
            type="button"
            className="btn"
            data-testid="quiz-leave-confirm"
            onClick={() => actions.confirmLeave()}
          >
            Leave
          </button>
        </div>
      )}
    </div>
  );
}
