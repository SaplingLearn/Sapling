"use client";
/**
 * The session-feedback follow-up questions, shared by the legacy tutor's
 * dialog (SessionFeedbackFlow) and Tutor V2's wrap-up (learn/WrapUpRating),
 * so both tutors ask the same things and send the same `selected_options`.
 */
import React from "react";

export const HELPFULNESS = [
  "Explanations clicked",
  "Right pace",
  "Got me unstuck",
  "Questions were sharp",
  "Matched my style",
  "Concepts felt linked",
];

export const FRICTION = [
  "Too slow",
  "Too surface",
  "Felt repetitive",
  "Off-topic",
  "Confusing",
  "Didn't match my level",
];

/** Toggle `value` in a multi-select list. */
export function toggled(list: string[], value: string): string[] {
  return list.includes(value) ? list.filter((x) => x !== value) : [...list, value];
}

export function ChipPicker({ label, options, selected, onToggle, disabled = false, testIdPrefix }: {
  label: string;
  options: string[];
  selected: string[];
  onToggle: (v: string) => void;
  disabled?: boolean;
  testIdPrefix?: string;
}) {
  return (
    <div>
      <div className="label-micro" style={{ marginBottom: 8 }}>{label}</div>
      <div role="group" aria-label={label} style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
        {options.map((o, i) => {
          const isSel = selected.includes(o);
          return (
            <button
              key={o}
              type="button"
              aria-pressed={isSel}
              disabled={disabled}
              data-testid={testIdPrefix ? `${testIdPrefix}-${i}` : undefined}
              onClick={() => onToggle(o)}
              style={{
                padding: "5px 11px",
                fontSize: 12,
                borderRadius: "var(--r-full)",
                background: isSel ? "var(--accent-soft)" : "transparent",
                color: isSel ? "var(--accent)" : "var(--text-dim)",
                border: `1px solid ${isSel ? "var(--accent-border)" : "var(--border)"}`,
                transition: "background var(--dur-fast) var(--ease), color var(--dur-fast) var(--ease), border-color var(--dur-fast) var(--ease)",
              }}
            >
              {o}
            </button>
          );
        })}
      </div>
    </div>
  );
}
