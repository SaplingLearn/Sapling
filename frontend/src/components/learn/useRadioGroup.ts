"use client";
// The WAI-ARIA radio-group keyboard pattern, shared by the learning loop's
// pick-one controls — the stated confidence (ConfidenceControl, spec §13 A127)
// and the multiple-choice options on the check-in and check cards (spec §13
// A135). The group is ONE tab stop: the chosen option, or the first while none
// is. The arrow keys move AND choose (wrapping); Home and End choose the ends.
// Space and Enter keep their native button behaviour and choose the focused
// option. Each option is a `<button>` the caller renders, spreading
// `optionProps(i)` onto it; the group element (role="radiogroup") and its
// accessible name are the caller's too.
import React from "react";

export function useRadioGroup<T>(values: readonly T[], value: T | null, onChange: (value: T) => void) {
  const refs = React.useRef<(HTMLElement | null)[]>([]);
  const chosen = value === null ? -1 : values.indexOf(value);
  const tabStop = chosen >= 0 ? chosen : 0;
  const last = values.length - 1;

  const choose = (index: number) => {
    const i = index < 0 ? last : index > last ? 0 : index;
    onChange(values[i]);
    refs.current[i]?.focus();
  };

  const onKeyDown = (event: React.KeyboardEvent, index: number) => {
    let target: number;
    switch (event.key) {
      case "ArrowRight":
      case "ArrowDown":
        target = index + 1;
        break;
      case "ArrowLeft":
      case "ArrowUp":
        target = index - 1;
        break;
      case "Home":
        target = 0;
        break;
      case "End":
        target = last;
        break;
      default:
        return; // Tab, Space and Enter keep their native behaviour
    }
    event.preventDefault();
    choose(target);
  };

  /** What option `index` needs: its ref, role, checked state, roving tab stop and keys. */
  const optionProps = (index: number) => ({
    ref: (el: HTMLElement | null) => {
      refs.current[index] = el;
    },
    role: "radio" as const,
    "aria-checked": values[index] === value,
    tabIndex: index === tabStop ? 0 : -1,
    onKeyDown: (event: React.KeyboardEvent) => onKeyDown(event, index),
  });

  /** Move focus into the group: onto its tab stop. */
  const focus = () => refs.current[tabStop]?.focus();

  return { optionProps, focus, focusFirst: () => refs.current[0]?.focus() };
}
