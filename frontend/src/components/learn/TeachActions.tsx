"use client";
// The actions between checks (moved out of LoopLearn.tsx unchanged): Continue
// after feedback (held by the W2.5 dwell), Check me, the plan's first concept,
// and the check's status line. LoopLearn decides every flag; this only draws.
import { clock, useCountdown } from "./question/HintLadder";
import React from "react";
import type { LoopPlanConcept } from "@/lib/api";
import { HYPERCORRECTION_DWELL_COPY } from "@/lib/hypercorrectionDwell";
import tutorStyles from "./tutor/tutor.module.css";
import { FEEDBACK_PENDING_COPY } from "./checkNote";
import styles from "./TeachActions.module.css";

export function TeachActions({
  feedback, feedbackPending, hold, continueDisabled, checkMeDisabled, pendingNote, teachStart, streaming,
  checkNote, checkNoteReported, continueRef, checkMeRef, teachStartRef, onContinue, onCheckMe, onTeachStart,
  next = null,
}: {
  /** The feedback phase: Continue shows, and Check me is no longer primary. */
  feedback: boolean;
  /** The feedback turn failed: Continue retries it, Check me waits. */
  feedbackPending: boolean;
  /** W2.5: a confident miss holds Continue while the student reads the feedback. */
  hold: boolean;
  continueDisabled: boolean;
  checkMeDisabled: boolean;
  /** Say why Check me waits (nothing else is said in the status line). */
  pendingNote: boolean;
  /** The plan's first concept, when "Start with …" is offered. */
  teachStart: LoopPlanConcept | undefined;
  streaming: boolean;
  checkNote: string | null;
  /** The note is the report's thanks (its own testid). */
  checkNoteReported: boolean;
  continueRef: React.RefObject<HTMLButtonElement | null>;
  checkMeRef: React.RefObject<HTMLButtonElement | null>;
  teachStartRef: React.RefObject<HTMLButtonElement | null>;
  onContinue: () => void;
  onCheckMe: () => void;
  onTeachStart: (concept: LoopPlanConcept) => void;
  /** `verdict_v2` on: Continue names where it goes ("Next: Stacks") and counts
   *  the hold down on itself; the verdict card says why it waits. */
  next?: { label: string; holdUntil: number | null } | null;
}) {
  const holdLeft = useCountdown(next?.holdUntil ?? null);
  const continueLabel = feedbackPending ? "Retry feedback"
    : !next ? "Continue"
    : hold && holdLeft > 0 ? `${next.label} in ${clock(holdLeft)}` : next.label;
  return (
    <div className={tutorStyles.chatActions}>
      {feedback && (
        <button
          ref={continueRef}
          data-testid="loop-continue"
          className={`btn btn--primary ${styles.press}`}
          onClick={onContinue}
          disabled={continueDisabled}
        >
          {continueLabel}
        </button>
      )}
      {feedback && hold && !next && (
        <span role="status" data-testid="loop-feedback-dwell" className={styles.note}>
          {HYPERCORRECTION_DWELL_COPY}
        </span>
      )}
      <button
        ref={checkMeRef}
        data-testid="loop-check-me"
        className={`${feedback ? "btn" : "btn btn--primary"} ${styles.press}`}
        onClick={onCheckMe}
        disabled={checkMeDisabled}
        title={feedbackPending ? FEEDBACK_PENDING_COPY : "Get a question on this concept"}
      >
        Check me
      </button>
      {pendingNote && <span role="status" className={styles.note}>{FEEDBACK_PENDING_COPY}</span>}
      {teachStart && (
        <button
          ref={teachStartRef}
          data-testid="loop-teach-start"
          className={`btn ${styles.press}`}
          onClick={() => onTeachStart(teachStart)}
          disabled={streaming}
        >
          Start with {teachStart.concept_name}
        </button>
      )}
      {/* Always in the DOM: a live region inserted with its text already in
          it is not reliably announced (spec §13 A135). */}
      <span aria-live="polite">
        {checkNote && (
          <span
            role="status"
            data-testid={checkNoteReported ? "loop-check-reported" : undefined}
            className={styles.note}
          >
            {checkNote}
          </span>
        )}
      </span>
    </div>
  );
}
