"use client";
// Learning loop (PKG-13): the budget pause banner (spec §3.5 hard level, §13
// A20/A26/A39). Shared by LoopLearn (`loop-budget-paused`) and DueQueue
// (`review-budget-paused`). A status line, never a toast: the pause is a
// state of the student's day, not an error, and nothing on a client timer
// clears it — the next successful tutor turn or a reload does.
import React from "react";

import { Icon } from "../Icon";

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
  return (
    <div
      role="status"
      data-testid={testId}
      data-reset-at={resetAt ?? ""}
      data-session-capped={sessionCapped ? "true" : "false"}
      style={{
        display: "flex",
        alignItems: "flex-start",
        gap: 10,
        padding: "10px 14px",
        borderRadius: "var(--r-md, 10px)",
        background: "var(--warn-soft)",
        color: "var(--text)",
        fontSize: 13,
        lineHeight: 1.45,
      }}
    >
      <span aria-hidden style={{ color: "var(--warn)", display: "inline-flex", paddingTop: 2 }}>
        <Icon name="bell" size={14} />
      </span>
      <div style={{ flex: 1, minWidth: 0 }}>
        {message}
        {children}
      </div>
    </div>
  );
}

/** "3:00 PM" when the reset is today, "Tue 3:00 PM" when it is not. */
export function formatResetAt(resetAt: string, now: Date = new Date()): string {
  const at = new Date(resetAt);
  if (Number.isNaN(at.getTime())) return "later";
  const sameDay = at.toDateString() === now.toDateString();
  return at.toLocaleString(undefined, {
    ...(sameDay ? {} : { weekday: "short" }),
    hour: "numeric",
    minute: "2-digit",
  });
}

/** The tutor-pause copy (spec §3.5, §13 A39). */
export function tutorPauseMessage(resetAt: string | null, sessionCapped: boolean): string {
  if (sessionCapped) return "Tutor chat paused for this session. Practice and review keep working.";
  if (!resetAt) return "Tutor chat paused for now. Practice and review keep working.";
  return `Tutor chat paused until ${formatResetAt(resetAt)}. Practice and review keep working.`;
}
