"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
import { usePathname, useSearchParams } from "next/navigation";
import { submitFeedback } from "@/lib/api";
import { useUser } from "@/context/UserContext";
import { useOverlayBehaviour } from "@/components/Dialog";
import {
  currentLearningSession,
  mayPrompt,
  notePulseFirstSeen,
  recordPrompt,
  releaseFeedbackSlot,
  tryClaimFeedbackSlot,
  whenFeedbackFree,
} from "@/lib/feedbackPacing";
import { useToast } from "./ToastProvider";
import { LONG_TEXT_MAX } from "@/lib/inputLimits";
import styles from "./FeedbackFlow.module.css";

/** How long a page is open before the pulse comes due. */
export const PULSE_DELAY_MS = 2 * 60_000;
/** Never over a task in progress: on these paths the pulse skips and waits
 *  for a later page instead (nothing is recorded, so the chance isn't spent). */
const NO_PULSE_PATHS = ["/quiz"];
// Numeric scale (serif numeral) keeps the tone "quiet library,"
// not mobile-game. Labels on hover for clarity.
const RATINGS: { value: number; label: string }[] = [
  { value: 1, label: "Struggling" },
  { value: 2, label: "Meh" },
  { value: 3, label: "Okay" },
  { value: 4, label: "Good" },
  { value: 5, label: "Great" },
];
const OPTIONS = [
  "Easy to use",
  "AI feels smart",
  "Helped me study",
  "Love the design",
  "Found a bug",
  "Missing a feature",
  "Confusing",
  "Too slow",
];

interface FeedbackFlowProps {
  /** Passive mode: comes due PULSE_DELAY_MS after mount; opens when
   *  lib/feedbackPacing.ts allows (past the new-student grace, never
   *  mid-learning or over a quiz, one per session, cooldowns). */
  passive?: boolean;
  /** Manual mode: caller controls open state. */
  open?: boolean;
  onClose?: () => void;
}

export function FeedbackFlow({ passive = true, open: openProp, onClose }: FeedbackFlowProps) {
  const { userId, isAuthenticated } = useUser();
  const toast = useToast();
  const searchParams = useSearchParams();
  const testOverride = searchParams.get("testFeedback") === "global";
  const pathname = usePathname();
  // Read when the timer fires, not when it was set: the student may have
  // started a quiz in the meantime.
  const pathnameRef = useRef(pathname);
  pathnameRef.current = pathname;

  const [open, setOpen] = useState<boolean>(openProp ?? false);
  const [rating, setRating] = useState<number | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [comment, setComment] = useState("");
  const [submitting, setSubmitting] = useState(false);


  useEffect(() => {
    if (!passive) return;
    if (!isAuthenticated) return;
    // The new-student grace counts from the first time the pulse could ask.
    notePulseFirstSeen();
    // Not worth a timer while the grace or a cooldown has it spent anyway.
    if (!testOverride && !mayPrompt("global", null)) return;
    let cancelWait = () => {};
    // Due at PULSE_DELAY_MS, but a learning activity in progress holds it until
    // the next natural break; then pacing decides again, against the session
    // the student is in by then. Spent there → dropped, never re-queued. Over a
    // quiz it skips without recording, so a later page may still ask (the path
    // is read when it fires, not when it was set). The session prompt may also
    // be on screen (#762): then skip, not stack.
    const show = () => {
      if (!testOverride && NO_PULSE_PATHS.some((p) => pathnameRef.current?.startsWith(p))) return;
      const session = currentLearningSession();
      if (!testOverride && !mayPrompt("global", session)) return;
      if (!tryClaimFeedbackSlot("global")) return;
      recordPrompt("global", session); // on open: a dismissal counts as shown
      setOpen(true);
    };
    // The test hook shows it, not paces it.
    const t = setTimeout(
      () => { cancelWait = whenFeedbackFree(show); },
      testOverride ? 1_000 : PULSE_DELAY_MS,
    );
    return () => { clearTimeout(t); cancelWait(); };
  }, [passive, isAuthenticated, testOverride]);

  // Give the one-prompt slot back if the shell unmounts mid-prompt.
  useEffect(() => () => releaseFeedbackSlot("global"), []);

  useEffect(() => {
    if (openProp !== undefined) setOpen(openProp);
  }, [openProp]);

  const close = useCallback(() => {
    setOpen(false);
    releaseFeedbackSlot("global");
    setRating(null);
    setSelected([]);
    setComment("");
    // A passive open was recorded when it opened; a manual one (the caller's
    // own form) still restarts the pulse's cooldown, as it always has.
    if (!passive) recordPrompt("global", null);
    onClose?.();
  }, [onClose, passive]);

  const toggleOption = (o: string) => {
    setSelected(prev => prev.includes(o) ? prev.filter(x => x !== o) : [...prev, o]);
  };

  const submit = async () => {
    if (!userId || rating === null) return;
    setSubmitting(true);
    try {
      await submitFeedback({
        user_id: userId,
        type: "global",
        rating,
        selected_options: selected,
        comment: comment.trim() || undefined,
      });
      toast.success("Thanks for the feedback!");
      close();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to submit.");
    } finally {
      setSubmitting(false);
    }
  };

  // Dialog's modal engine (scroll lock, focus in and back out, Escape, the
  // Tab trap) under this flow's own card.
  const { panelRef, onKeyDown } = useOverlayBehaviour({ open, onClose: () => { if (!submitting) close(); } });

  if (!open) return null;

  return (
    <div className={styles.backdrop} onClick={() => !submitting && close()} onKeyDown={onKeyDown}>
      <div ref={panelRef} tabIndex={-1} role="dialog" aria-modal="true" aria-labelledby="feedback-pulse-title" onClick={e => e.stopPropagation()} className={styles.card}>
        <div className={styles.header}>
          <div id="feedback-pulse-title" className={`h-serif ${styles.pulseTitle}`}>What's clicking?</div>
          <button className="btn btn--ghost btn--sm" onClick={() => close()} aria-label="Close">×</button>
        </div>
        <div className={`body-serif ${styles.lede}`}>
          A quick pulse. Nothing is a wrong answer.
        </div>

        <div className={styles.ratings}>
          {RATINGS.map(r => (
            <button
              key={r.value}
              onClick={() => setRating(r.value)}
              aria-label={r.label}
              title={r.label}
              data-selected={rating === r.value}
              className={`h-serif ${styles.rating}`}
            >
              {r.value}
            </button>
          ))}
        </div>

        <div className={`label-micro ${styles.fieldLabel}`}>What stood out?</div>
        <div className={styles.chips}>
          {OPTIONS.map(o => (
            <button
              key={o}
              onClick={() => toggleOption(o)}
              data-selected={selected.includes(o)}
              className={styles.chip}
            >
              {o}
            </button>
          ))}
        </div>

        <div className={`label-micro ${styles.fieldLabel}`}>Anything else? (optional)</div>
        <textarea
          value={comment}
          maxLength={LONG_TEXT_MAX}
          onChange={e => setComment(e.target.value)}
          placeholder="Share a thought…"
          rows={3}
          className={styles.textarea}
        />

        <div className={styles.footer}>
          <button className="btn" onClick={() => close()} disabled={submitting}>Not now</button>
          <button className="btn btn--primary" onClick={submit} disabled={rating === null || submitting}>
            {submitting ? "Sending…" : "Submit"}
          </button>
        </div>
      </div>
    </div>
  );
}
