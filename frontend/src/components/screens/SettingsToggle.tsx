"use client";

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
      style={{
        flexShrink: 0,
        width: 36,
        height: 20,
        padding: 0,
        border: "none",
        borderRadius: "var(--r-full)",
        background: on ? "var(--accent)" : "var(--bg-soft)",
        position: "relative",
        cursor: disabled ? "not-allowed" : "pointer",
        opacity: disabled ? 0.5 : 1,
        transition: "all var(--dur) var(--ease)",
      }}
    >
      <span
        aria-hidden
        style={{
          position: "absolute",
          top: 2,
          left: on ? 18 : 2,
          width: 16,
          height: 16,
          borderRadius: "50%",
          background: "#fff",
          boxShadow: "var(--shadow-sm)",
          transition: "all var(--dur) var(--ease)",
        }}
      />
    </button>
  );
}
