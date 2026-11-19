"use client";
import React, { useEffect, useState } from "react";
import { submitFeedback } from "@/lib/api";
import { useUser } from "@/context/UserContext";
import { mayPrompt, recordPrompt, releaseFeedbackSlot, tryClaimFeedbackSlot } from "@/lib/feedbackPacing";
import { SessionRatingScale } from "./SessionRatingScale";

const THANKS_COPY = "Thanks — this helps tune your tutor.";
const FAILED_COPY = "Couldn't send your rating. Try again.";

/**
 * Whether the wrap-up of `sessionId` asks "How was that session?". It is asked
 * on the wrap-up itself, never later over another page (the shell's
 * SessionFeedbackGlobal used to open it once the student left /learn, over
 * Study). lib/feedbackPacing.ts still decides: once per session, the session
 * prompt's cooldown and the gap between any two prompts. Called once, when the
 * wrap-up arrives — an event, so before the commit whose effect lifts the
 * session's feedback hold: the shell's pulse, waiting for that release, then
 * finds this ask recorded and the slot taken, and does not open on top of it.
 */
export function claimWrapUpAsk(sessionId: string): boolean {
  if (!mayPrompt("session", sessionId) || !tryClaimFeedbackSlot("session")) return false;
  recordPrompt("session", sessionId); // asked when shown: a skip counts too
  return true;
}

type Sent = "idle" | "sending" | "sent" | "failed";

/** The wrap-up's rating card (shown only when `claimWrapUpAsk` said so). One
 *  click sends the rating; the slot is given back when the wrap-up goes. */
export function WrapUpRating({ sessionId, topic }: { sessionId: string; topic?: string }) {
  const { userId } = useUser();
  const [rating, setRating] = useState<number | null>(null);
  const [sent, setSent] = useState<Sent>("idle");
  useEffect(() => () => releaseFeedbackSlot("session"), []);

  const choose = async (value: number) => {
    if (!userId || sent === "sending" || sent === "sent") return;
    setRating(value);
    setSent("sending");
    try {
      await submitFeedback({ user_id: userId, type: "session", rating: value, selected_options: [], session_id: sessionId, topic });
      setSent("sent");
    } catch {
      setSent("failed");
    }
  };

  return (
    <section data-testid="loop-close-rating" aria-labelledby="loop-close-rating-h" className="card" style={{ padding: "var(--pad-lg)", display: "flex", flexDirection: "column", gap: 10 }}>
      <span className="label-micro">Your feedback</span>
      <h3 id="loop-close-rating-h" className="h-serif" style={{ margin: 0, fontSize: 18 }}>How was that session?</h3>
      <SessionRatingScale value={rating} onSelect={(value) => void choose(value)} disabled={sent === "sending" || sent === "sent"} testIdPrefix="loop-close-rating" />
      {/* Always in the DOM, so the outcome is announced (spec §13 A135). */}
      <div aria-live="polite" style={{ fontSize: 13, color: "var(--text-muted)" }}>
        {sent === "sent" && <span role="status" data-testid="loop-close-rating-sent">{THANKS_COPY}</span>}
        {sent === "failed" && <span role="status">{FAILED_COPY}</span>}
      </div>
    </section>
  );
}
