"use client";
import React, { useEffect, useState } from "react";
import { submitFeedback } from "@/lib/api";
import { useUser } from "@/context/UserContext";
import { mayPrompt, recordPrompt, releaseFeedbackSlot, tryClaimFeedbackSlot } from "@/lib/feedbackPacing";
import { LONG_TEXT_MAX } from "@/lib/inputLimits";
import { ChipPicker, FRICTION, HELPFULNESS, toggled } from "../sessionFeedbackOptions";
import { SessionRatingScale } from "./SessionRatingScale";

const THANKS_COPY = "Thanks — this helps tune your tutor.";
const FAILED_COPY = "Couldn't send your feedback. Try again.";

/**
 * Whether the wrap-up of `sessionId` asks "How was that session?". It is asked
 * on the wrap-up itself, never later over another page (the shell's
 * SessionFeedbackGlobal used to open it once the student left /learn, over
 * Study). lib/feedbackPacing.ts still decides: once per session, the session
 * prompt's cooldown and the gap between any two prompts. Called once, when the
 * wrap-up arrives — an event, so before the commit whose effect lifts the
 * session's feedback hold: the shell's pulse, waiting for that release, then
 * finds this ask recorded and the slot taken, and does not open on top of it.
 * The slot is given back when the wrap-up goes (LoopLearn releases it with the
 * ask, so a wrap-up left before this card mounted never keeps it).
 */
export function claimWrapUpAsk(sessionId: string): boolean {
  if (!mayPrompt("session", sessionId) || !tryClaimFeedbackSlot("session")) return false;
  recordPrompt("session", sessionId); // asked when shown: a skip counts too
  return true;
}

export type WrapUpAsk = { sessionId: string; topic?: string };

/**
 * The wrap-up's ask (PR #866 review U9): visible only while a close is on
 * screen, and the feedback slot `claimWrapUpAsk` took is given back whenever
 * the visible ask goes — the close cleared, replaced, or the screen unmounted —
 * not only when WrapUpRating unmounts, which a wrap-up left before the card
 * mounted never did.
 */
export function useWrapUpAsk(closeShown: unknown): readonly [WrapUpAsk | null, (ask: WrapUpAsk | null) => void] {
  const [ask, setAsk] = useState<WrapUpAsk | null>(null);
  const visible = closeShown ? ask : null;
  useEffect(() => (visible ? () => releaseFeedbackSlot("session") : undefined), [visible]);
  return [visible, setAsk] as const;
}

type Sent = "idle" | "sending" | "sent" | "failed";

/**
 * The wrap-up's feedback card (shown only when `claimWrapUpAsk` said so): the
 * 1–4 rating, then the legacy dialog's follow-ups on the same card — what
 * worked, any friction, an optional note — sent together as ONE session
 * feedback row, the shape SessionFeedbackFlow sends (PR #866 review U9).
 */
export function WrapUpRating({ sessionId, topic }: { sessionId: string; topic?: string }) {
  const { userId } = useUser();
  const [rating, setRating] = useState<number | null>(null);
  const [helpful, setHelpful] = useState<string[]>([]);
  const [friction, setFriction] = useState<string[]>([]);
  const [comment, setComment] = useState("");
  const [sent, setSent] = useState<Sent>("idle");
  useEffect(() => () => releaseFeedbackSlot("session"), []);
  const locked = sent === "sending" || sent === "sent";

  const send = async () => {
    if (!userId || rating === null || locked) return;
    setSent("sending");
    try {
      await submitFeedback({
        user_id: userId,
        type: "session",
        rating,
        selected_options: [...helpful, ...friction],
        comment: comment.trim() || undefined,
        session_id: sessionId,
        topic,
      });
      setSent("sent");
    } catch {
      setSent("failed");
    }
  };

  return (
    <section data-testid="loop-close-rating" aria-labelledby="loop-close-rating-h" className="card fade-in" style={{ padding: "var(--pad-lg)", display: "flex", flexDirection: "column", gap: 12 }}>
      <span className="label-micro">Your feedback</span>
      <h3 id="loop-close-rating-h" className="h-serif" style={{ margin: 0, fontSize: 18 }}>How was that session?</h3>
      <SessionRatingScale value={rating} onSelect={setRating} disabled={locked} testIdPrefix="loop-close-rating" />
      {rating !== null && sent !== "sent" && (
        <div data-testid="loop-close-rating-details" className="fade-in" style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <ChipPicker label="What worked?" options={HELPFULNESS} selected={helpful} disabled={locked}
            onToggle={(v) => setHelpful((l) => toggled(l, v))} testIdPrefix="loop-close-rating-helpful" />
          <ChipPicker label="Any friction?" options={FRICTION} selected={friction} disabled={locked}
            onToggle={(v) => setFriction((l) => toggled(l, v))} testIdPrefix="loop-close-rating-friction" />
          <label style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            <span className="label-micro">Anything else to add?</span>
            <textarea
              data-testid="loop-close-rating-comment"
              value={comment}
              maxLength={LONG_TEXT_MAX}
              disabled={locked}
              onChange={(e) => setComment(e.target.value)}
              placeholder="Optional note…"
              rows={3}
              style={{ width: "100%", padding: "10px 14px", fontSize: 13, border: "1px solid var(--border)", borderRadius: "var(--r-sm)", background: "var(--bg-input)", fontFamily: "inherit", resize: "vertical", boxSizing: "border-box" }}
            />
          </label>
          <div>
            <button type="button" data-testid="loop-close-rating-send" className="btn btn--primary" disabled={locked} onClick={() => void send()}>
              {sent === "sending" ? "Sending…" : "Send feedback"}
            </button>
          </div>
        </div>
      )}
      {/* Always in the DOM, so the outcome is announced (spec §13 A135). */}
      <div aria-live="polite" style={{ fontSize: 13, color: "var(--text-muted)" }}>
        {sent === "sent" && <span role="status" data-testid="loop-close-rating-sent">{THANKS_COPY}</span>}
        {sent === "failed" && <span role="status">{FAILED_COPY}</span>}
      </div>
    </section>
  );
}
