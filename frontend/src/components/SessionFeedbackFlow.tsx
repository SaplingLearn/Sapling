"use client";

import React, { useCallback, useState } from "react";
import { submitFeedback } from "@/lib/api";
import { useUser } from "@/context/UserContext";
import { useScrollLock } from "@/lib/useScrollLock";
import { useToast } from "./ToastProvider";
import { LONG_TEXT_MAX } from "@/lib/inputLimits";
// Numeric scale — the brand's tone is "quiet library," not emoji reactions —
// with its two ends labelled under it (shared with the Tutor's wrap-up).
import { SessionRatingScale } from "./learn/SessionRatingScale";
import { ChipPicker, FRICTION, HELPFULNESS, toggled } from "./sessionFeedbackOptions";
import styles from "./FeedbackFlow.module.css";

/** The follow-up's steps: rating, what worked, friction, a note. */
const STEPS = [0, 1, 2, 3];

export interface SessionFeedbackContext {
  sessionId?: string;
  topic?: string;
}

interface SessionFeedbackFlowProps {
  open: boolean;
  context?: SessionFeedbackContext;
  onClose: () => void;
}

export function SessionFeedbackFlow({ open, context, onClose }: SessionFeedbackFlowProps) {
  const { userId } = useUser();
  const toast = useToast();

  const [step, setStep] = useState(0);
  const [rating, setRating] = useState<number | null>(null);
  const [helpful, setHelpful] = useState<string[]>([]);
  const [friction, setFriction] = useState<string[]>([]);
  const [comment, setComment] = useState("");
  const [submitting, setSubmitting] = useState(false);

  useScrollLock(open);

  // Pacing (cooldown, one prompt per session) is recorded by the opener when
  // the prompt opens — lib/feedbackPacing.ts — so every close here counts.
  const close = useCallback(() => {
    setStep(0);
    setRating(null);
    setHelpful([]);
    setFriction([]);
    setComment("");
    onClose();
  }, [onClose]);

  const toggle = (list: string[], setList: (v: string[]) => void, v: string) => setList(toggled(list, v));

  const submit = async () => {
    if (!userId || rating === null) return;
    setSubmitting(true);
    try {
      await submitFeedback({
        user_id: userId,
        type: "session",
        rating,
        selected_options: [...helpful, ...friction],
        comment: comment.trim() || undefined,
        session_id: context?.sessionId,
        topic: context?.topic,
      });
      toast.success("Thanks — this helps tune your tutor.");
      close();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to submit.");
    } finally {
      setSubmitting(false);
    }
  };

  if (!open) return null;

  const canNext = step === 0 ? rating !== null : true;

  return (
    <div className={styles.backdrop} onClick={() => !submitting && close()}>
      <div onClick={e => e.stopPropagation()} className={styles.card}>
        <div className={styles.header}>
          <div className={`h-serif ${styles.sessionTitle}`}>How was that session?</div>
          <button className="btn btn--ghost btn--sm" onClick={() => close()} aria-label="Close">×</button>
        </div>

        {context?.topic && (
          <div className={styles.topic}>
            on <span className={styles.topicName}>{context.topic}</span>
          </div>
        )}

        <div className={styles.steps}>
          {STEPS.map(i => (
            <div key={i} className={styles.stepSegment} data-done={i <= step} />
          ))}
        </div>

        <div key={step} className={styles.stepBody}>
          {step === 0 && (
            <div>
              <div className={`label-micro ${styles.stepLabel}`}>How did it feel?</div>
              <SessionRatingScale value={rating} onSelect={setRating} />
            </div>
          )}

          {step === 1 && (
            <ChipPicker
              label="What worked?"
              options={HELPFULNESS}
              selected={helpful}
              onToggle={v => toggle(helpful, setHelpful, v)}
            />
          )}

          {step === 2 && (
            <ChipPicker
              label="Any friction?"
              options={FRICTION}
              selected={friction}
              onToggle={v => toggle(friction, setFriction, v)}
            />
          )}

          {step === 3 && (
            <div>
              <div className={`label-micro ${styles.fieldLabel}`}>Anything else to add?</div>
              <textarea
                value={comment}
                maxLength={LONG_TEXT_MAX}
                onChange={e => setComment(e.target.value)}
                placeholder="Optional note…"
                rows={4}
                className={styles.textarea}
              />
            </div>
          )}
        </div>

        <div className={`${styles.footer} ${styles.footerSplit}`}>
          {step > 0 ? (
            <button className="btn" onClick={() => setStep(step - 1)} disabled={submitting}>Back</button>
          ) : (
            <button className="btn btn--ghost" onClick={() => close()} disabled={submitting}>Skip</button>
          )}
          {step < 3 ? (
            <button className="btn btn--primary" onClick={() => setStep(step + 1)} disabled={!canNext || submitting}>
              Next
            </button>
          ) : (
            <button className="btn btn--primary" onClick={submit} disabled={rating === null || submitting}>
              {submitting ? "Sending…" : "Submit"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
