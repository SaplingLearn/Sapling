"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
import { usePathname, useSearchParams } from "next/navigation";
import { submitFeedback } from "@/lib/api";
import { useUser } from "@/context/UserContext";
import { useScrollLock } from "@/lib/useScrollLock";
import { releaseFeedbackSlot, tryClaimFeedbackSlot } from "@/lib/feedbackSlot";
import { useToast } from "./ToastProvider";

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

  useScrollLock(open);

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

  if (!open) return null;

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
          <div className="h-serif" style={{ fontSize: 24 }}>What's clicking?</div>
          <button className="btn btn--ghost btn--sm" onClick={() => close(true)} aria-label="Close">×</button>
        </div>
        <div className="body-serif" style={{ fontSize: 14, color: "var(--text-dim)", marginBottom: 16 }}>
          A quick pulse. Nothing is a wrong answer.
        </div>

        <div style={{ display: "flex", justifyContent: "space-between", gap: 6, marginBottom: 20 }}>
          {RATINGS.map(r => {
            const selectedRating = rating === r.value;
            return (
              <button
                key={r.value}
                onClick={() => setRating(r.value)}
                aria-label={r.label}
                title={r.label}
                className="h-serif"
                style={{
                  flex: 1,
                  padding: "14px 4px",
                  fontSize: 22,
                  fontWeight: 500,
                  color: selectedRating ? "var(--accent)" : "var(--text-dim)",
                  borderRadius: "var(--r-md)",
                  border: `1px solid ${selectedRating ? "var(--accent-border)" : "var(--border)"}`,
                  background: selectedRating ? "var(--accent-soft)" : "var(--bg-panel)",
                  transition: "background var(--dur-fast) var(--ease), color var(--dur-fast) var(--ease)",
                }}
              >
                {r.value}
              </button>
            );
          })}
        </div>

        <div className="label-micro" style={{ marginBottom: 6 }}>What stood out?</div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 14 }}>
          {OPTIONS.map(o => {
            const isSel = selected.includes(o);
            return (
              <button
                key={o}
                onClick={() => toggleOption(o)}
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

        <div className="label-micro" style={{ marginBottom: 6 }}>Anything else? (optional)</div>
        <textarea
          value={comment}
          onChange={e => setComment(e.target.value)}
          placeholder="Share a thought…"
          rows={3}
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

        <div style={{ display: "flex", gap: 8, justifyContent: "flex-end", marginTop: 16 }}>
          <button className="btn" onClick={() => close(true)} disabled={submitting}>Not now</button>
          <button className="btn btn--primary" onClick={submit} disabled={rating === null || submitting}>
            {submitting ? "Sending…" : "Submit"}
          </button>
        </div>
      </div>
    </div>
  );
}
