"use client";
import React from "react";
import styles from "./SessionRatingScale.module.css";

/**
 * The "How was that session?" scale, as `feedback.rating` stores it (type
 * "session", routes/feedback.py): 1 is the worst session, 4 the best. The
 * wrap-up asks it inline (WrapUpRating) and the legacy tutor's prompt asks it
 * in a dialog (SessionFeedbackFlow); both show these words.
 */
export const SESSION_RATINGS: readonly { value: number; label: string }[] = [
  { value: 1, label: "Frustrating" },
  { value: 2, label: "Just okay" },
  { value: 3, label: "Productive" },
  { value: 4, label: "Great session" },
];

/** The four numbers, with the scale's two ends labelled under them, so "1" and
 *  "4" never read as an unexplained score. Each number's accessible name starts
 *  with its visible digit (WCAG 2.5.3) and says what it means. */
export function SessionRatingScale({
  value,
  onSelect,
  disabled,
  testIdPrefix,
}: {
  value: number | null;
  onSelect: (rating: number) => void;
  disabled?: boolean;
  testIdPrefix?: string;
}) {
  const first = SESSION_RATINGS[0];
  const last = SESSION_RATINGS[SESSION_RATINGS.length - 1];
  return (
    <div className={styles.scale}>
      <div className={styles.row}>
        {SESSION_RATINGS.map((r) => {
          const sel = value === r.value;
          return (
            <button
              key={r.value}
              type="button"
              data-testid={testIdPrefix ? `${testIdPrefix}-${r.value}` : undefined}
              aria-label={`${r.value} – ${r.label}`}
              aria-pressed={sel}
              title={r.label}
              disabled={disabled}
              onClick={() => onSelect(r.value)}
              className={`h-serif ${styles.digit}`}
            >
              {r.value}
            </button>
          );
        })}
      </div>
      <div aria-hidden className={styles.ends}>
        <span>{first.value} = {first.label}</span>
        <span>{last.value} = {last.label}</span>
      </div>
    </div>
  );
}
