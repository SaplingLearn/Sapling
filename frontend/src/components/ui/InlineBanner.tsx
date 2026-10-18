"use client";
import React from "react";

/**
 * InlineBanner — a full-width strip under a page header (#537).
 *
 * The quiz's "You left a quiz on Recursion — 2 of 5 answered · Resume ·
 * Discard" line. There was no precedent for this anywhere in the app (Learn
 * offers an ordinary "Resume session" button and nothing else), and Dashboard
 * and Study both plausibly want the same shape later, so it lands here rather
 * than inside the quiz.
 *
 * `role="status"` because it appears in response to state the user didn't just
 * ask about — a resumable attempt found on another device should be announced,
 * not silently painted.
 */
export interface InlineBannerProps {
  children: React.ReactNode;
  /** Right-aligned controls. Usually a secondary button and a link button. */
  actions?: React.ReactNode;
  tone?: "accent" | "neutral";
  testid?: string;
}

export function InlineBanner({ children, actions, tone = "accent", testid }: InlineBannerProps) {
  return (
    <div className={`inline-banner inline-banner--${tone}`} role="status" data-testid={testid}>
      <div className="inline-banner__body">{children}</div>
      {actions && <div className="inline-banner__actions">{actions}</div>}
    </div>
  );
}
