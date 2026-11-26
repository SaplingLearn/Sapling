"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
import { usePathname, useSearchParams } from "next/navigation";
import { submitFeedback } from "@/lib/api";
import { useUser } from "@/context/UserContext";
import Dialog from "@/components/Dialog";
import { releaseFeedbackSlot, tryClaimFeedbackSlot } from "@/lib/feedbackSlot";
import { useToast } from "./ToastProvider";
import { LONG_TEXT_MAX } from "@/lib/inputLimits";
import { cn } from "@/lib/cn";

const DAY_MS = 24 * 60 * 60 * 1000;
/** How long a page is open before the pulse asks. */
export const PULSE_DELAY_MS = 2 * 60_000;
/** Between one pulse and the next, however it was closed. */
export const PULSE_COOLDOWN_MS = 14 * DAY_MS;
/** A new student isn't asked how it's going in their first days. */
export const PULSE_GRACE_MS = 3 * DAY_MS;
const STORAGE_KEY = "sapling_last_feedback";
export const FIRST_SEEN_KEY = "sapling_feedback_first_seen";
/** Never over a task in progress: the pulse waits for a later page instead
 *  (nothing is recorded, so the chance isn't spent). */
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
  /** Passive mode: auto-opens after PULSE_DELAY_MS, past the grace and cooldown. */
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
    let cancelled = false;
    const now = Date.now();
    let firstSeen = 0;
    let last = 0;
    try {
      firstSeen = Number(localStorage.getItem(FIRST_SEEN_KEY) ?? "0");
      if (!firstSeen) localStorage.setItem(FIRST_SEEN_KEY, String(now));
      last = Number(localStorage.getItem(STORAGE_KEY) ?? "0");
    } catch {
      return; // no storage, no way to keep a cooldown: don't ask at all
    }
    const settledIn = firstSeen > 0 && now - firstSeen > PULSE_GRACE_MS;
    const cooledDown = !last || now - last > PULSE_COOLDOWN_MS;
    if (!testOverride && !(settledIn && cooledDown)) return;
    // The session prompt may already be on screen (#762) — then skip this
    // pulse rather than stack a second modal on it.
    const t = setTimeout(() => {
      if (cancelled) return;
      if (!testOverride && NO_PULSE_PATHS.some(p => pathnameRef.current?.startsWith(p))) return;
      if (tryClaimFeedbackSlot("global")) setOpen(true);
    }, testOverride ? 1_000 : PULSE_DELAY_MS); // the test hook shows it, not paces it
    return () => { cancelled = true; clearTimeout(t); };
  }, [passive, isAuthenticated, testOverride]);

  // Give the one-prompt slot back if the shell unmounts mid-prompt.
  useEffect(() => () => releaseFeedbackSlot("global"), []);

  useEffect(() => {
    if (openProp !== undefined) setOpen(openProp);
  }, [openProp]);

  const close = useCallback((recordCooldown: boolean) => {
    setOpen(false);
    releaseFeedbackSlot("global");
    setRating(null);
    setSelected([]);
    setComment("");
    if (recordCooldown) localStorage.setItem(STORAGE_KEY, String(Date.now()));
    onClose?.();
  }, [onClose]);

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
      close(true);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to submit.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog
      open={open}
      onClose={() => { if (!submitting) close(true); }}
      labelledBy="feedback-pulse-title"
      width="440px"
      zIndex={200}
      showCloseButton={false}
    >
        <div className="flex justify-between items-center mb-3">
          <div id="feedback-pulse-title" className="h-serif text-[24px]">What's clicking?</div>
          <button className="btn btn--ghost btn--sm" onClick={() => close(true)} aria-label="Close">×</button>
        </div>
        <div className="body-serif text-base text-text-dim mb-4">
          A quick pulse. Nothing is a wrong answer.
        </div>

        <div className="flex justify-between gap-1.5 mb-5">
          {RATINGS.map(r => {
            const selectedRating = rating === r.value;
            return (
              <button
                key={r.value}
                onClick={() => setRating(r.value)}
                aria-label={r.label}
                title={r.label}
                className={cn(cn("h-serif", "flex-1 py-3.5 px-1 text-2xl font-medium rounded-md [transition:background_var(--dur-fast)_var(--ease),_color_var(--dur-fast)_var(--ease)]", selectedRating ? "text-accent" : "text-text-dim", selectedRating ? "bg-accent-soft" : "bg-bg-panel"), selectedRating ? "border border-accent-border" : "border border-border")}
              >
                {r.value}
              </button>
            );
          })}
        </div>

        <div className="label-micro mb-1.5">What stood out?</div>
        <div className="flex flex-wrap gap-1.5 mb-3.5">
          {OPTIONS.map(o => {
            const isSel = selected.includes(o);
            return (
              <button
                key={o}
                onClick={() => toggleOption(o)}
                className={cn(cn("py-[5px] px-[11px] text-sm rounded-[var(--r-full)]", isSel ? "bg-accent-soft" : "bg-transparent", isSel ? "text-accent" : "text-text-dim"), isSel ? "border border-accent-border" : "border border-border")}
              >
                {o}
              </button>
            );
          })}
        </div>

        <div className="label-micro mb-1.5">Anything else? (optional)</div>
        <textarea
          value={comment}
          maxLength={LONG_TEXT_MAX}
          onChange={e => setComment(e.target.value)}
          placeholder="Share a thought…"
          rows={3}
          className="w-full py-2.5 px-3.5 text-md border border-border rounded-sm bg-bg-input [font-family:inherit] resize-y"
        />

        <div className="flex gap-2 justify-end mt-4">
          <button className="btn" onClick={() => close(true)} disabled={submitting}>Not now</button>
          <button className="btn btn--primary" onClick={submit} disabled={rating === null || submitting}>
            {submitting ? "Sending…" : "Submit"}
          </button>
        </div>
    </Dialog>
  );
}
