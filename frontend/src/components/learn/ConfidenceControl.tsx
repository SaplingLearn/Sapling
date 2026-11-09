"use client";
// The student's stated confidence (learning-loop spec §13 A127): "Guessing" /
// "Fairly sure" / "Sure" on the loop's check and probe cards and on Study's
// review card — never the post-test, which stays tool-free and minimal. It is
// optional: a student who skips it sends nothing (the backend records the
// confidence as absent, never as a default), and it never delays or blocks
// submitting (choosing makes no request; Submit never waits on it). The backend
// maps the label onto the §3.3 misconception rule's scale and keeps it with the
// evidence for the admin's calibration report.
//
// Accessibility: a labelled radio group (the WAI-ARIA radio pattern, shared
// with the multiple-choice options through `useRadioGroup`). One tab stop —
// the chosen level, or the first while none is — the arrow keys move AND
// choose (wrapping; Home / End for the ends), Space / Enter chooses the
// focused level, and every level shows a focus ring (`.option:focus-visible`).
// "Clear" takes a choice back, so skipping stays possible after a click. Every
// testid is `${testIdPrefix}…`, written at the call site.
import React from "react";
import type { StudentConfidence } from "@/lib/api";
import styles from "./ConfidenceControl.module.css";
import { useRadioGroup } from "./useRadioGroup";

/** The three levels, in scale order (backend params.STUDENT_CONFIDENCE_LEVELS). */
export const CONFIDENCE_LEVELS: readonly { level: StudentConfidence; label: string }[] = [
  { level: "guessing", label: "Guessing" },
  { level: "fairly_sure", label: "Fairly sure" },
  { level: "sure", label: "Sure" },
];

const LEVELS = CONFIDENCE_LEVELS.map((o) => o.level);

export function ConfidenceControl({
  testIdPrefix,
  value,
  onChange,
  disabled = false,
}: {
  testIdPrefix: string;
  /** The chosen level; null = none (skipped). */
  value: StudentConfidence | null;
  onChange: (value: StudentConfidence | null) => void;
  disabled?: boolean;
}) {
  const labelId = React.useId();
  const group = useRadioGroup(LEVELS, value, onChange);

  return (
    <div className={styles.row}>
      <span id={labelId} className={styles.label}>
        How sure are you? <span className={styles.optional}>(optional)</span>
      </span>
      <div role="radiogroup" aria-labelledby={labelId} data-testid={testIdPrefix} className={styles.group}>
        {CONFIDENCE_LEVELS.map((o, i) => (
          <button
            key={o.level}
            {...group.optionProps(i)}
            type="button"
            data-testid={`${testIdPrefix}-${o.level}`}
            className={styles.option}
            disabled={disabled}
            onClick={() => onChange(o.level)}
          >
            {o.label}
          </button>
        ))}
      </div>
      {value !== null && (
        <button
          type="button"
          data-testid={`${testIdPrefix}-clear`}
          className={`btn btn--sm btn--ghost ${styles.clear}`}
          disabled={disabled}
          onClick={() => {
            onChange(null);
            group.focusFirst(); // the button goes: keep the keyboard in the group
          }}
        >
          Clear
        </button>
      )}
    </div>
  );
}
