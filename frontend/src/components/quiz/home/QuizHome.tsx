"use client";

/**
 * STUB — Wave 3 (B1) replaces the body. The PROPS are the seam and must not
 * change: `QuizScreen` composes exactly this shape from `useQuizHome`,
 * `useQuizConfig` and `useQuizSession`, and A2's tests pin it.
 *
 * What this placeholder is for: it renders enough to drive the machine by hand
 * end to end (pick the proposal, press Start) so the data layer can be exercised
 * before a single pixel of the real screen exists.
 *
 * The real screen is §5 B1: resume strip, "Ready for you" proposal with its
 * neighbourhood, two alternatives, the review-everything-due row, the grouped
 * pick list, the concept and adjust dialogs, and the empty states.
 */

import React from "react";
import type { QuizActions } from "@/lib/quiz/useQuizSession";
import type { QuizHome as QuizHomeData } from "@/lib/quiz/useQuizHome";
import type { EntryRequest } from "@/lib/quiz/source";
import type { QuizConfig, QuizPrefs, QuizSession } from "@/lib/quiz/types";
import { queueFor } from "@/lib/quiz/proposals";
import { QUEUE_COUNT } from "@/lib/quiz/session";

export interface QuizHomeProps {
  userId: string;
  home: QuizHomeData;
  config: QuizConfig | null;
  prefs: QuizPrefs;
  entry: EntryRequest;
  session: QuizSession;
  actions: QuizActions;
}

export function QuizHome({ home, session, actions, entry }: QuizHomeProps) {
  const primary = home.primary;

  const startPrimary = () => {
    if (!primary) return;
    actions.start({
      intent: "practice",
      scope: { kind: "concept", conceptId: primary.node.id },
      conceptId: primary.node.id,
      courseId: primary.node.course_id ?? null,
    });
  };

  const startDue = () => {
    const queue = queueFor("due", home.nodes);
    if (queue.length === 0) return;
    actions.start(
      {
        intent: "review",
        scope: { kind: "due", queue },
        conceptId: queue[0],
        courseId: home.nodes.find(n => n.id === queue[0])?.course_id ?? null,
      },
      { ...session.config, count: QUEUE_COUNT },
    );
  };

  return (
    <div className="quiz-stub" data-testid="quiz-home">
      <h2 className="h-serif">Quiz</h2>
      <p className="quiz-stub__phase label-micro">
        {session.phase} · {home.status}
        {entry.scope === "due" ? " · due" : ""}
      </p>

      {home.resumable && (
        <p data-testid="quiz-resume-strip">
          You left a quiz on {home.resumable.attempt.concept_node_id} —{" "}
          {home.resumable.answered} answered
        </p>
      )}

      <p data-testid="quiz-proposal">
        {primary ? primary.node.concept_name : "Nothing to propose yet"}
        {primary ? ` · ${primary.rationale}` : ""}
      </p>
      <p>{home.primaryDescription ?? ""}</p>
      <p>
        {session.config.count} questions, {session.config.difficulty}
        {session.config.feedback === "as-you-go" ? " · answers as you go" : ""}
      </p>

      <div className="quiz-stub__actions">
        <button
          type="button"
          className="btn btn--primary"
          data-testid="quiz-start"
          disabled={!primary}
          onClick={startPrimary}
        >
          Start
        </button>
        {home.resumable && (
          <button
            type="button"
            className="btn"
            data-testid="quiz-resume"
            onClick={() => actions.resume(home.resumable!.attempt.quiz_id)}
          >
            Resume
          </button>
        )}
        {home.due.count > 0 && (
          <button type="button" className="btn" data-testid="quiz-review-due" onClick={startDue}>
            Review everything due ({home.due.count})
          </button>
        )}
        <button
          type="button"
          className="btn btn--ghost"
          data-testid="quiz-cancel"
          onClick={() => actions.exit()}
        >
          Cancel
        </button>
      </div>
    </div>
  );
}
