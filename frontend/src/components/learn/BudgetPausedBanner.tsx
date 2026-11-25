"use client";
// Learning loop (PKG-13): the budget pause banner (spec §3.5 hard level, §13
// A20/A26/A39). Shared by LoopLearn (`loop-budget-paused`) and DueQueue
// (`review-budget-paused`). A status line, never a toast: the pause is a
// state of the student's day, not an error, and nothing on a client timer
// clears it — the next successful tutor turn or a reload does.
import React from "react";
import { motion } from "framer-motion";

import type { LoopBudgetPause } from "@/lib/api";
import { useMotionPresets } from "@/lib/motion";
import { Icon } from "../Icon";
import styles from "./BudgetPausedBanner.module.css";

const MS_PER_DAY = 86_400_000;
const DAYS_PER_WEEK = 7;

export function BudgetPausedBanner({
  testId,
  resetAt,
  sessionCapped = false,
  message,
  children,
}: {
  testId: string;
  resetAt: string | null;
  sessionCapped?: boolean;
  message: React.ReactNode;
  children?: React.ReactNode;
}) {
  // The pause rises into place when it starts (`fadeUp`).
  const m = useMotionPresets();
  return (
    <motion.div
      {...m.fadeUp}
      role="status"
      data-testid={testId}
      data-reset-at={resetAt ?? ""}
      data-session-capped={sessionCapped ? "true" : "false"}
      className={styles.banner}
    >
      <span aria-hidden className={styles.icon}>
        <Icon name="bell" size={14} />
      </span>
      <div className={styles.body}>
        {message}
        {children}
      </div>
    </motion.div>
  );
}

/** Whole local calendar days from `now`'s date to `at`'s. */
const daysAhead = (at: Date, now: Date) =>
  Math.round(
    (new Date(at.getFullYear(), at.getMonth(), at.getDate()).getTime()
      - new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime()) / MS_PER_DAY,
  );

/** "3:00 PM" when the reset is today, "Tue 3:00 PM" within the week, and
 *  "Dec 1, 7:00 PM" further out (#866 K18: the monthly cap lifts on the 1st, and
 *  a bare weekday weeks away read as this week's). */
export function formatResetAt(resetAt: string, now: Date = new Date()): string {
  const at = new Date(resetAt);
  if (Number.isNaN(at.getTime())) return "later";
  const days = daysAhead(at, now);
  const day = days === 0 ? {} : days > 0 && days < DAYS_PER_WEEK ? { weekday: "short" as const } : { month: "short" as const, day: "numeric" as const };
  return at.toLocaleString(undefined, { ...day, hour: "numeric", minute: "2-digit" });
}

/** The tutor-pause copy (spec §3.5, §13 A39). `pauseNovice` (#866 K35): the hard
 *  level holds checks on novice-band concepts too (A20), so "practice keeps
 *  working" would promise a "Check me" that cannot pose one. `aiLimit` (#866 K11):
 *  the daily limit on every AI feature pauses checks too, so it never says practice works. */
export function tutorPauseMessage(resetAt: string | null, sessionCapped: boolean, pauseNovice = false, aiLimit = false): string {
  if (aiLimit) return `You've reached today's limit for AI features. It resets ${resetAt ? `at ${formatResetAt(resetAt)}` : "tomorrow"}.`;
  const when = sessionCapped ? " for this session" : resetAt ? ` until ${formatResetAt(resetAt)}` : " for now";
  const rest = pauseNovice
    ? "Review keeps working, but checks on concepts you're just starting are paused too."
    : "Practice and review keep working.";
  return `Tutor chat paused${when}. ${rest}`;
}

/** #866 K35: "Check me" answered 429 — at the hard level the concept's check is
 *  held (a novice-band concept, A20): say so beside the button. */
export function checkPausedNote(pause: LoopBudgetPause): string {
  const until = pause.sessionCapped ? " for this session" : pause.resetAt ? ` until ${formatResetAt(pause.resetAt)}` : " for now";
  return `Checks on this concept wait${until}: you're just starting it, and the AI budget is paused. Keep going with review on Study.`;
}
