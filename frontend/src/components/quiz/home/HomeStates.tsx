"use client";

/**
 * Quiz home's frame and its states with no proposal: the resume strip above
 * everything, the two columns, the loading skeleton, the error card and the
 * empty states.
 *
 * The non-component helpers here return their elements directly (they are
 * called, not rendered as `<X />`), so each state keeps the exact element
 * type it had inline in `QuizHome` and React reconciles a state change the
 * same way it always did.
 */

import React from "react";
import { Button, EmptyState, InlineBanner } from "@/components/ui";
import { Skeleton } from "@/components/Skeleton";
import type { AttemptSummary } from "@/lib/quiz/types";
import type { ResumableQuiz } from "@/lib/quiz/useQuizHome";
import type { GraphNode } from "@/lib/types";
import { resumeNameFor, resumeTotalFor, type HomeView } from "./homeView";

/** The neighbourhood window's height while the tree loads (`home.css`). */
const GRAPH_SKELETON_HEIGHT = 340;

export interface ResumeStripProps {
  resumable: ResumableQuiz;
  nodes: GraphNode[];
  attempts: AttemptSummary[];
  onResume: (quizId: string) => void;
  onDiscard: (quizId: string) => void;
}

// A true full-bleed band: it renders OUTSIDE the content column (A2's
// `.quiz-body--home` is padding-free for exactly this), so `InlineBanner`'s
// own page padding and bottom rule reach both edges under the TopBar with
// nothing here overriding them.
export function ResumeStrip({ resumable, nodes, attempts, onResume, onDiscard }: ResumeStripProps) {
  const resumeName = resumeNameFor(resumable, nodes, attempts);
  const resumeTotal = resumeTotalFor(resumable);
  return (
    <InlineBanner
      testid="quiz-resume-strip"
      actions={
        <>
          <Button data-testid="quiz-resume" onClick={() => onResume(resumable.attempt.quiz_id)}>
            Resume
          </Button>
          <Button
            variant="link"
            data-testid="quiz-resume-discard"
            onClick={() => onDiscard(resumable.attempt.quiz_id)}
          >
            Discard
          </Button>
        </>
      }
    >
      {`You left a quiz on ${resumeName} — ${resumable.answered} of ${resumeTotal} answered`}
    </InlineBanner>
  );
}

/** The two columns, with whatever each one holds. */
export function homeColumns(lead: React.ReactNode, side: React.ReactNode) {
  return (
    <div className="quiz-home__grid">
      <div className="quiz-home__lead">{lead}</div>
      <div className="quiz-home__grid-divider" />
      {side}
    </div>
  );
}

export function skeletonColumns() {
  return homeColumns(
    <div className="quiz-home__skeleton-main">
      <Skeleton width={240} height={32} />
      <Skeleton width={220} height={12} />
      <Skeleton width={380} height={13} />
      <Skeleton width={340} height={13} />
      <Skeleton width={160} height={16} />
      <Skeleton width="100%" height={GRAPH_SKELETON_HEIGHT} />
      <Skeleton width={120} height={34} />
    </div>,
    <div className="quiz-home__topics-col">
      <Skeleton width="100%" height={28} />
      <div className="quiz-home__skeleton-rows">
        {[0, 1, 2, 3, 4, 5].map(i => (
          <Skeleton key={i} width="100%" height={18} />
        ))}
      </div>
    </div>,
  );
}

export function errorCard(message: string | undefined, onRetry: () => void) {
  return (
    <div className="quiz-error" role="alert" data-testid="quiz-home-error">
      <h2 className="h-serif quiz-error__title">We couldn&apos;t load your tree</h2>
      <p className="quiz-error__body">{message}</p>
      <div className="quiz-error__actions">
        <Button variant="primary" data-testid="quiz-home-retry" onClick={onRetry}>
          Retry
        </Button>
      </div>
    </div>
  );
}

export function noCoursesState() {
  return (
    <EmptyState
      testid="quiz-empty-state"
      title="Add a course to start quizzing"
      body="Quizzes come from the concepts on your tree, and your tree grows out of your courses."
      action={{ label: "Go to your dashboard", href: "/dashboard" }}
    />
  );
}

export function emptyTreeState() {
  return (
    <EmptyState
      testid="quiz-empty-state"
      title="Your tree is empty"
      body="Upload notes or talk to the tutor and concepts will appear here."
      action={
        <>
          <a className="btn btn--primary" href="/library">
            Go to your library
          </a>
          <a className="btn" href="/learn">
            Talk to the tutor
          </a>
        </>
      }
    />
  );
}

// Every concept is mastered: there is nothing to propose, but every
// concept is still in the list beside this, so it is a signpost rather
// than a dead end.
export function masteredState() {
  return (
    <EmptyState
      testid="quiz-empty-state"
      title="Nothing needs review right now"
      body="Every concept on your tree is in good shape. Pick one from the list to quiz it anyway."
    />
  );
}

/** The body of every arrival but the ordinary home. */
export function stateBody(
  view: Exclude<HomeView, "home">,
  errorMessage: string | undefined,
  onRetry: () => void,
) {
  if (view === "error") return errorCard(errorMessage, onRetry);
  if (view === "loading") return skeletonColumns();
  if (view === "no-courses") return noCoursesState();
  return emptyTreeState();
}
