"use client";
import React from "react";

/**
 * Switch — a binary on/off control (`role="switch"`).
 *
 * NOT `<Toggle>`: that is the pick-one pill. A switch is for a single
 * setting that is either on or off, and announces its state as checked.
 */
export function Switch({
  checked,
  onChange,
  label,
  disabled,
  testid,
}: {
  checked: boolean;
  onChange: (next: boolean) => void;
  /** Accessible name — the setting the switch controls. */
  label: string;
  disabled?: boolean;
  testid?: string;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      className="switch"
      data-testid={testid}
      onClick={(e) => {
        e.stopPropagation();
        onChange(!checked);
      }}
    >
      <span className="switch__knob" aria-hidden />
    </button>
  );
}
