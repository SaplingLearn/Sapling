"use client";
import React from "react";

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
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      <div style={{ display: "flex", gap: 8, justifyContent: "space-between" }}>
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
              className="h-serif"
              style={{
                flex: 1,
                padding: "12px 4px",
                fontSize: 20,
                fontWeight: 500,
                color: sel ? "var(--accent)" : "var(--text-dim)",
                borderRadius: "var(--r-md)",
                border: `1px solid ${sel ? "var(--accent-border)" : "var(--border)"}`,
                background: sel ? "var(--accent-soft)" : "var(--bg-panel)",
                transition: "background var(--dur-fast) var(--ease), color var(--dur-fast) var(--ease)",
              }}
            >
              {r.value}
            </button>
          );
        })}
      </div>
      <div aria-hidden style={{ display: "flex", justifyContent: "space-between", gap: 8, fontSize: 12, color: "var(--text-muted)" }}>
        <span>{first.value} = {first.label}</span>
        <span>{last.value} = {last.label}</span>
      </div>
    </div>
  );
}
