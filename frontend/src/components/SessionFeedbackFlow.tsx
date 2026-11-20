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
    <div
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,0.4)",
        zIndex: 200,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
      }}
      onClick={() => !submitting && close()}
    >
      <div
        onClick={e => e.stopPropagation()}
        style={{
          width: 440,
          maxWidth: "calc(100vw - 32px)",
          background: "var(--bg-panel)",
          borderRadius: "var(--r-lg)",
          padding: 28,
          boxShadow: "var(--shadow-lg)",
        }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
          <div className="h-serif" style={{ fontSize: 22 }}>How was that session?</div>
          <button className="btn btn--ghost btn--sm" onClick={() => close()} aria-label="Close">×</button>
        </div>

        {context?.topic && (
          <div style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 16 }}>
            on <span style={{ color: "var(--text-dim)" }}>{context.topic}</span>
          </div>
        )}

        <div style={{ display: "flex", gap: 6, marginBottom: 20 }}>
          {[0, 1, 2, 3].map(i => (
            <div
              key={i}
              style={{
                flex: 1,
                height: 4,
                borderRadius: "var(--r-full)",
                background: i <= step ? "var(--accent)" : "var(--bg-soft)",
              }}
            />
          ))}
        </div>

        {step === 0 && (
          <div>
            <div className="label-micro" style={{ marginBottom: 8 }}>How did it feel?</div>
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
            <div className="label-micro" style={{ marginBottom: 6 }}>Anything else to add?</div>
            <textarea
              value={comment}
              maxLength={LONG_TEXT_MAX}
              onChange={e => setComment(e.target.value)}
              placeholder="Optional note…"
              rows={4}
              style={{
                width: "100%",
                padding: "10px 14px",
                fontSize: 13,
                border: "1px solid var(--border)",
                borderRadius: "var(--r-sm)",
                background: "var(--bg-input)",
                fontFamily: "inherit",
                resize: "vertical",
              }}
            />
          </div>
        )}

        <div style={{ display: "flex", gap: 8, justifyContent: "space-between", marginTop: 18 }}>
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
