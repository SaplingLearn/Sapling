"use client";
import styles from "./SettingsToggle.module.css";

/**
 * The settings on/off switch: a real `<button role="switch">`, so it is
 * focusable, keyboard-operable and announces its state. Name it with
 * `ariaLabelledBy` (the id of its visible label).
 */
export function Toggle({
  on,
  onChange,
  disabled = false,
  ariaLabelledBy,
  testId,
}: {
  on: boolean;
  onChange: (v: boolean) => void;
  disabled?: boolean;
  ariaLabelledBy?: string;
  testId?: string;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      aria-labelledby={ariaLabelledBy}
      data-testid={testId}
      disabled={disabled}
      onClick={() => onChange(!on)}
      className={styles.toggle}
    >
      <span aria-hidden className={styles.knob} />
    </button>
  );
}
