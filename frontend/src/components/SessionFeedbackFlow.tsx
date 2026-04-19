"use client";

import React, { useCallback, useState } from "react";
import { submitFeedback } from "@/lib/api";
import { useUser } from "@/context/UserContext";
import { useBodyScrollLock } from "@/lib/useBodyScrollLock";
import { useToast } from "./ToastProvider";

export const SESSION_COOLDOWN_MS = 2 * 24 * 60 * 60 * 1000;
export const SESSION_COOLDOWN_KEY = "sapling_last_session_feedback";
export const SESSION_END_COUNT_KEY = "sapling_session_end_count";

const RATINGS: { value: number; emoji: string; label: string }[] = [
  { value: 1, emoji: "😕", label: "Frustrating" },
  { value: 2, emoji: "😐", label: "Just okay" },
  { value: 3, emoji: "🙂", label: "Productive" },
  { value: 4, emoji: "🎉", label: "Great session" },
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

  useBodyScrollLock(open);

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
      onClick={() => !submitting && close(true)}
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
          <button className="btn btn--ghost btn--sm" onClick={() => close(true)} aria-label="Close">×</button>
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
            <div style={{ display: "flex", gap: 8, justifyContent: "space-between" }}>
              {RATINGS.map(r => {
                const sel = rating === r.value;
                return (
                  <button
                    key={r.value}
                    onClick={() => setRating(r.value)}
                    aria-label={r.label}
                    style={{
                      flex: 1,
                      padding: "14px 4px",
                      borderRadius: "var(--r-md)",
                      border: `1.5px solid ${sel ? "var(--accent)" : "var(--border)"}`,
                      background: sel ? "var(--accent-soft)" : "var(--bg-panel)",
                      fontSize: 22,
                    }}
                  >
                    {r.emoji}
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
            <div className="label-micro" style={{ marginBottom: 6 }}>Anything else to add?</div>
            <textarea
              value={comment}
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
      </div>
    </div>
  );
}

function ChipPicker({ label, options, selected, onToggle }: {
  label: string; options: string[]; selected: string[]; onToggle: (v: string) => void;
}) {
  return (
    <div>
      <div className="label-micro" style={{ marginBottom: 8 }}>{label}</div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
        {options.map(o => {
          const isSel = selected.includes(o);
          return (
            <button
              key={o}
              onClick={() => onToggle(o)}
              style={{
                padding: "5px 11px",
                fontSize: 12,
                borderRadius: "var(--r-full)",
                background: isSel ? "var(--accent-soft)" : "transparent",
                color: isSel ? "var(--accent)" : "var(--text-dim)",
                border: `1px solid ${isSel ? "var(--accent-border)" : "var(--border)"}`,
              }}
            >
              {o}
            </button>
          );
        })}
      </div>
    </div>
  );
}
