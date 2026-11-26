"use client";

import React, { useCallback, useState } from "react";
import { submitFeedback } from "@/lib/api";
import { useUser } from "@/context/UserContext";
import Dialog from "@/components/Dialog";
import { useToast } from "./ToastProvider";
import { LONG_TEXT_MAX } from "@/lib/inputLimits";
import { cn } from "@/lib/cn";

export const SESSION_COOLDOWN_MS = 7 * 24 * 60 * 60 * 1000;
export const SESSION_COOLDOWN_KEY = "sapling_last_session_feedback";

// Numeric scale — the brand's tone is "quiet library," not emoji reactions.
const RATINGS: { value: number; label: string }[] = [
  { value: 1, label: "Frustrating" },
  { value: 2, label: "Just okay" },
  { value: 3, label: "Productive" },
  { value: 4, label: "Great session" },
];

const HELPFULNESS = [
  "Explanations clicked",
  "Right pace",
  "Got me unstuck",
  "Questions were sharp",
  "Matched my style",
  "Concepts felt linked",
];

const FRICTION = [
  "Too slow",
  "Too surface",
  "Felt repetitive",
  "Off-topic",
  "Confusing",
  "Didn't match my level",
];

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


  const close = useCallback((recordCooldown: boolean) => {
    if (recordCooldown) localStorage.setItem(SESSION_COOLDOWN_KEY, String(Date.now()));
    setStep(0);
    setRating(null);
    setHelpful([]);
    setFriction([]);
    setComment("");
    onClose();
  }, [onClose]);

  const toggle = (list: string[], setList: (v: string[]) => void, v: string) => {
    setList(list.includes(v) ? list.filter(x => x !== v) : [...list, v]);
  };

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
      close(true);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to submit.");
    } finally {
      setSubmitting(false);
    }
  };

  const canNext = step === 0 ? rating !== null : true;

  return (
    <Dialog
      open={open}
      onClose={() => { if (!submitting) close(true); }}
      labelledBy="session-feedback-title"
      width="440px"
      zIndex={200}
      showCloseButton={false}
    >
        <div className="flex justify-between items-center mb-3">
          <div id="session-feedback-title" className="h-serif text-2xl">How was that session?</div>
          <button className="btn btn--ghost btn--sm" onClick={() => close(true)} aria-label="Close">×</button>
        </div>

        {context?.topic && (
          <div className="text-sm text-text-muted mb-4">
            on <span className="text-text-dim">{context.topic}</span>
          </div>
        )}

        <div className="flex gap-1.5 mb-5">
          {[0, 1, 2, 3].map(i => (
            <div
              key={i}
              className={cn("flex-1 h-1 rounded-[var(--r-full)]", i <= step ? "bg-accent" : "bg-bg-soft")}
            />
          ))}
        </div>

        {step === 0 && (
          <div>
            <div className="label-micro mb-2">How did it feel?</div>
            <div className="flex gap-2 justify-between">
              {RATINGS.map(r => {
                const sel = rating === r.value;
                return (
                  <button
                    key={r.value}
                    onClick={() => setRating(r.value)}
                    aria-label={r.label}
                    title={r.label}
                    className={cn(cn("h-serif", "flex-1 py-3.5 px-1 text-[20px] font-medium rounded-md [transition:background_var(--dur-fast)_var(--ease),_color_var(--dur-fast)_var(--ease)]", sel ? "text-accent" : "text-text-dim", sel ? "bg-accent-soft" : "bg-bg-panel"), sel ? "border border-accent-border" : "border border-border")}
                  >
                    {r.value}
                  </button>
                );
              })}
            </div>
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
            <div className="label-micro mb-1.5">Anything else to add?</div>
            <textarea
              value={comment}
              maxLength={LONG_TEXT_MAX}
              onChange={e => setComment(e.target.value)}
              placeholder="Optional note…"
              rows={4}
              className="w-full py-2.5 px-3.5 text-md border border-border rounded-sm bg-bg-input [font-family:inherit] resize-y"
            />
          </div>
        )}

        <div className="flex gap-2 justify-between mt-4.5">
          {step > 0 ? (
            <button className="btn" onClick={() => setStep(step - 1)} disabled={submitting}>Back</button>
          ) : (
            <button className="btn btn--ghost" onClick={() => close(true)} disabled={submitting}>Skip</button>
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
    </Dialog>
  );
}

function ChipPicker({ label, options, selected, onToggle }: {
  label: string; options: string[]; selected: string[]; onToggle: (v: string) => void;
}) {
  return (
    <div>
      <div className="label-micro mb-2">{label}</div>
      <div className="flex flex-wrap gap-1.5">
        {options.map(o => {
          const isSel = selected.includes(o);
          return (
            <button
              key={o}
              onClick={() => onToggle(o)}
              className={cn(cn("py-[5px] px-[11px] text-sm rounded-[var(--r-full)]", isSel ? "bg-accent-soft" : "bg-transparent", isSel ? "text-accent" : "text-text-dim"), isSel ? "border border-accent-border" : "border border-border")}
            >
              {o}
            </button>
          );
        })}
      </div>
    </div>
  );
}
