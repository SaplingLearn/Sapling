"use client";
import React from "react";

/**
 * SegmentedControl — the design's mono/uppercase pick-one row (#537).
 *
 * NOT `<Toggle>`: that is the filled pill, a different visual language. This
 * one is `.label-micro` type with a 2px accent underline on the selected
 * option, which is the mechanic four screens already re-implement privately
 * (Achievements, Admin, Learn's mobile tabs, FlashcardImportModal) — none of
 * them shared, none of them mono. This is the shared one.
 *
 * Semantics are a real radiogroup: one tab stop for the whole control (roving
 * tabindex), arrows move AND select, Home/End jump to the ends, and disabled
 * options are skipped rather than focused-and-refused.
 *
 * The option list is always the caller's — the quiz reads its counts and
 * difficulties off `GET /api/quiz/config` and never enumerates them in code.
 */
export interface SegmentedControlProps<V extends string | number> {
  options: { value: V; label: string; disabled?: boolean }[];
  value: V;
  onChange: (v: V) => void;
  ariaLabel?: string;
  labelledBy?: string;
  testid?: string;
}

export function SegmentedControl<V extends string | number>({
  options,
  value,
  onChange,
  ariaLabel,
  labelledBy,
  testid,
}: SegmentedControlProps<V>) {
  const refs = React.useRef(new Map<V, HTMLButtonElement>());

  const enabled = options.filter((o) => !o.disabled);
  const selectedIndex = enabled.findIndex((o) => o.value === value);
  // Nothing selected yet → the first enabled option carries the tab stop, so
  // the control is always reachable.
  const tabStop = selectedIndex >= 0 ? value : enabled[0]?.value;

  const move = (delta: number) => {
    if (enabled.length === 0) return;
    const from = selectedIndex >= 0 ? selectedIndex : 0;
    const next = enabled[(from + delta + enabled.length) % enabled.length];
    onChange(next.value);
    refs.current.get(next.value)?.focus();
  };

  const jump = (index: number) => {
    const target = enabled[index];
    if (!target) return;
    onChange(target.value);
    refs.current.get(target.value)?.focus();
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    switch (e.key) {
      case "ArrowRight":
      case "ArrowDown":
        e.preventDefault();
        move(1);
        break;
      case "ArrowLeft":
      case "ArrowUp":
        e.preventDefault();
        move(-1);
        break;
      case "Home":
        e.preventDefault();
        jump(0);
        break;
      case "End":
        e.preventDefault();
        jump(enabled.length - 1);
        break;
      default:
        break;
    }
  };

  return (
    <div
      className="seg"
      role="radiogroup"
      aria-label={ariaLabel}
      aria-labelledby={labelledBy}
      data-testid={testid}
      onKeyDown={onKeyDown}
    >
      {options.map((option) => {
        const checked = option.value === value;
        return (
          <button
            key={String(option.value)}
            ref={(el) => {
              if (el) refs.current.set(option.value, el);
              else refs.current.delete(option.value);
            }}
            type="button"
            role="radio"
            aria-checked={checked}
            aria-disabled={option.disabled || undefined}
            tabIndex={option.value === tabStop ? 0 : -1}
            className="seg__opt label-micro"
            data-testid={testid ? `${testid}-${option.value}` : undefined}
            onClick={() => {
              if (option.disabled) return;
              onChange(option.value);
            }}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}
